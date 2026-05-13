"""bank-statement-analizer — FastAPI application factory.

Lifespan
--------
Calls ``build_checkpointer()`` on startup, stores the saver on
``app.state.checkpointer``, compiles the LangGraph graph and stores it on
``app.state.graph``.  Calls the teardown callable on shutdown so the SQLite
(or Postgres) connection is released cleanly.

CORS
----
Controlled by env var ``FRONTEND_ORIGIN`` (default ``http://localhost:5173``).
Methods and headers are narrowly scoped.

Logging
-------
Every request emits method + path + status + latency via a thin ASGI middleware.
Uses ``get_logger`` exclusively — no ``print``.
"""

from __future__ import annotations

import os
import time
from collections.abc import (
    AsyncIterator,  # noqa: TC003 — runtime-required by asynccontextmanager return annotation
)
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.logging import get_logger
from src.api.routers.extract import router as extract_router
from src.api.routers.extract_stream import router as extract_stream_router
from src.api.routers.reviews import router as reviews_router
from src.graph.builder import build_graph
from src.graph.checkpointer import build_async_checkpointer

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the async checkpointer and compile the graph on startup.

    We use the async checkpointer variant (AsyncPostgresSaver /
    AsyncSqliteSaver) so ``await graph.ainvoke(...)`` in the /extract
    endpoint can issue real awaits on the checkpoint backend.  The sync
    PostgresSaver does NOT implement aget_tuple and would NotImplementedError
    on the first checkpoint read; see src/graph/checkpointer.py
    build_async_checkpointer for the docstring reference.
    """
    saver, teardown = await build_async_checkpointer()
    app.state.checkpointer = saver
    app.state.graph = build_graph(checkpointer=saver)
    # Initialise the pending-reviews schema.  Done here (not at import time)
    # so the Docker volume mount has happened before the sqlite file is
    # created at /app/data/reviews.sqlite.
    from src.api.reviews import init_reviews_db

    init_reviews_db()
    logger.info("lifespan: async checkpointer ready, graph compiled, reviews DB ready")
    try:
        yield
    finally:
        await teardown()
        logger.info("lifespan: checkpointer connection closed")


# ---------------------------------------------------------------------------
# Request-logging middleware (≤ 15 LOC, no third-party deps)
# ---------------------------------------------------------------------------


async def _log_requests(request: Request, call_next: object) -> Response:
    """Emit method + path + status + latency for every request."""
    start = time.perf_counter()
    # call_next is typed as Callable by Starlette's middleware protocol
    response: Response = await call_next(request)  # type: ignore[operator]
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Return a configured FastAPI application.

    Module-level ``app = create_app()`` is the uvicorn target
    (``uvicorn src.api.main:app``).
    """
    application = FastAPI(
        title="bank-statement-analizer",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # ------------------------------------------------------------------
    # CORS — narrowly scoped
    # ------------------------------------------------------------------
    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type"],
    )

    # ------------------------------------------------------------------
    # Request-logging middleware
    # ------------------------------------------------------------------
    application.middleware("http")(_log_requests)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    application.include_router(extract_router)
    application.include_router(extract_stream_router)
    application.include_router(reviews_router)

    # ------------------------------------------------------------------
    # Health probes
    # ------------------------------------------------------------------

    @application.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness probe — always 200 when the process is alive."""
        return {"status": "ok"}

    @application.get("/readyz", tags=["ops"])
    def readyz() -> Response:
        """Readiness probe — 503 until the API key is present and graph is built."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "ANTHROPIC_API_KEY missing"},
            )
        checkpointer = getattr(application.state, "checkpointer", None)
        if checkpointer is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "checkpointer not initialised"},
            )
        return Response(
            content='{"status":"ready"}',
            media_type="application/json",
            status_code=200,
        )

    return application


# ---------------------------------------------------------------------------
# Module-level export — uvicorn target
# ---------------------------------------------------------------------------

app = create_app()

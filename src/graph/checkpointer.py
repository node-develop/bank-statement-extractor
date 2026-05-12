"""Checkpointer factory for the bank-statement-analizer LangGraph pipeline.

Usage (FastAPI lifespan)
------------------------
The preferred pattern for a long-lived service is to call
``build_checkpointer()`` inside an ``asynccontextmanager`` lifespan and keep
the returned saver alive for the duration of the process::

    from contextlib import asynccontextmanager
    from src.graph.checkpointer import build_checkpointer

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        saver, teardown = build_checkpointer()
        app.state.checkpointer = saver
        yield
        teardown()

Environment variables
---------------------
``LANGGRAPH_CHECKPOINTER``
    ``"sqlite"`` (default) or ``"postgres"``.

``LANGGRAPH_SQLITE_PATH``
    Path to the SQLite database file.  Defaults to ``"./graph.sqlite"``.
    Pass ``":memory:"`` for in-process ephemeral storage (tests).

``DATABASE_URL``
    Required when ``LANGGRAPH_CHECKPOINTER=postgres``.
    Example: ``postgresql://user:pass@host:5432/dbname``.

``LANGGRAPH_STRICT_MSGPACK``
    When ``"true"`` (default), the SQLite saver rejects checkpoint payloads
    that contain types not in the safe allow-list.  **Do not set to "false"
    in production** — it would allow arbitrary Python objects to be
    deserialised from a user-controlled database row, which is a code-
    execution risk.

Security recommendation
-----------------------
Always leave ``LANGGRAPH_STRICT_MSGPACK=true`` (the default here).  The
variable is read by the underlying ``langgraph-checkpoint-sqlite`` library;
this module simply ensures the default is safe before the library reads it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)

# Type alias for the teardown callable returned alongside the saver.
_Teardown = Callable[[], None]

# Accepted values for LANGGRAPH_CHECKPOINTER
_BACKEND_SQLITE = "sqlite"
_BACKEND_POSTGRES = "postgres"
_BACKEND_MEMORY = "memory"  # convenience for tests


def build_checkpointer() -> tuple[object, _Teardown]:
    """Return ``(saver, teardown)`` for the configured checkpointer backend.

    The ``saver`` is a fully initialised ``BaseCheckpointSaver`` ready to be
    passed to ``StateGraph.compile(checkpointer=saver)``.

    The ``teardown`` callable must be invoked when the application shuts down
    (e.g. in the FastAPI lifespan ``finally`` block or the ``asynccontextmanager``
    exit path).  For SQLite it closes the underlying connection; for Postgres it
    exits the connection pool context manager.

    Raises
    ------
    RuntimeError
        If ``LANGGRAPH_CHECKPOINTER=postgres`` but ``DATABASE_URL`` is unset.
    ValueError
        If ``LANGGRAPH_CHECKPOINTER`` is set to an unrecognised value.
    """
    # Enforce safe msgpack serialisation BEFORE the library reads the env var.
    if not os.environ.get("LANGGRAPH_STRICT_MSGPACK"):
        os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
        logger.debug("LANGGRAPH_STRICT_MSGPACK defaulted to 'true'")

    backend = os.environ.get("LANGGRAPH_CHECKPOINTER", _BACKEND_SQLITE).lower()

    if backend == _BACKEND_MEMORY:
        saver = InMemorySaver()
        return saver, lambda: None

    if backend == _BACKEND_SQLITE:
        return _build_sqlite()

    if backend == _BACKEND_POSTGRES:
        return _build_postgres()

    raise ValueError(
        f"Unrecognised LANGGRAPH_CHECKPOINTER value: {backend!r}. "
        f"Expected one of: {_BACKEND_SQLITE!r}, {_BACKEND_POSTGRES!r}, "
        f"{_BACKEND_MEMORY!r}."
    )


def _build_sqlite() -> tuple[SqliteSaver, _Teardown]:
    """Construct a long-lived ``SqliteSaver`` via the documented public API.

    ``SqliteSaver.from_conn_string`` is the public factory confirmed by
    context7 docs (reference.langchain.com/python/langgraph/checkpoints).
    We call ``__enter__`` / ``__exit__`` explicitly so the FastAPI lifespan
    controls the connection lifetime — identical pattern to ``_build_postgres``.
    Works for both ``":memory:"`` (tests) and file paths.
    """
    db_path = os.environ.get("LANGGRAPH_SQLITE_PATH", "./graph.sqlite")
    logger.info("Building SQLite checkpointer at %s", db_path)

    cm = SqliteSaver.from_conn_string(db_path)
    saver = cm.__enter__()

    def teardown() -> None:
        logger.info("Closing SQLite checkpointer connection (%s)", db_path)
        cm.__exit__(None, None, None)

    return saver, teardown


def _build_postgres() -> tuple[object, _Teardown]:
    """Construct a ``PostgresSaver`` from ``DATABASE_URL``.

    The optional ``langgraph-checkpoint-postgres`` extra must be installed::

        uv sync --extra postgres

    We enter the context manager explicitly and return a teardown that exits
    it, giving the FastAPI lifespan full control over the connection lifetime.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("PostgresSaver is not installed. Run: uv sync --extra postgres") from exc

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("LANGGRAPH_CHECKPOINTER=postgres requires DATABASE_URL to be set.")

    logger.info("Building Postgres checkpointer (DATABASE_URL is set)")
    cm = PostgresSaver.from_conn_string(db_url)
    saver = cm.__enter__()
    # setup() runs schema migrations (CREATE TABLE IF NOT EXISTS checkpoints …).
    # Must be called before graph.invoke(); confirmed by context7 docs at
    # reference.langchain.com/python/langgraph/checkpoints.
    saver.setup()

    def teardown() -> None:
        logger.info("Closing Postgres checkpointer connection")
        cm.__exit__(None, None, None)

    return saver, teardown

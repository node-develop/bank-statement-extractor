"""Checkpointer factory for the bank-statement-analizer LangGraph pipeline.

Backends
--------
- ``sqlite`` (default) — ``SqliteSaver`` (sync) / ``AsyncSqliteSaver`` (async).
  Single file on disk; perfect for local-dev and a small test deployment.
- ``memory`` — ``InMemorySaver``; tests only.

Why no Postgres? The Ixonia test task is single-tenant and the LangGraph
checkpoint volume per extraction is small. SQLite with a persisted Docker
volume covers the durability requirement; Postgres adds a second container
without buying anything for this use case. A future deployment can swap
backends here without touching graph or API code.

Environment variables
---------------------
``LANGGRAPH_CHECKPOINTER``
    ``"sqlite"`` (default) or ``"memory"``.

``LANGGRAPH_SQLITE_PATH``
    Path to the SQLite database file. Defaults to ``"./graph.sqlite"``.
    Pass ``":memory:"`` for in-process ephemeral storage.

``LANGGRAPH_STRICT_MSGPACK``
    When ``"true"`` (default), the SQLite saver rejects checkpoint payloads
    that contain types not in the safe allow-list. **Do not set to "false"
    in production** — it would allow arbitrary Python objects to be
    deserialised from a user-controlled database row, which is a
    code-execution risk.

API contract
------------
Two factories live here:

- :func:`build_checkpointer` — synchronous; returns ``(saver, teardown)``.
  Used by ``src/evals/run.py`` (CLI) and any non-async caller.
- :func:`build_async_checkpointer` — asynchronous; returns
  ``(saver, async_teardown)``. Used by ``src/api/main.py`` lifespan because
  the FastAPI endpoint awaits ``graph.ainvoke(...)``, which calls
  ``await checkpointer.aget_tuple(...)`` — only the ``aio`` variants
  implement that.  (Confirmed by docs.langchain.com/oss/python/langgraph/add-memory.)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)

# Type aliases for the teardown callables returned alongside the saver.
_Teardown = Callable[[], None]
_AsyncTeardown = Callable[[], Awaitable[None]]

# Accepted values for LANGGRAPH_CHECKPOINTER
_BACKEND_SQLITE = "sqlite"
_BACKEND_MEMORY = "memory"


def _ensure_safe_msgpack() -> None:
    """Default LANGGRAPH_STRICT_MSGPACK to ``true`` before any saver loads."""
    if not os.environ.get("LANGGRAPH_STRICT_MSGPACK"):
        os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
        logger.debug("LANGGRAPH_STRICT_MSGPACK defaulted to 'true'")


def _backend() -> str:
    return os.environ.get("LANGGRAPH_CHECKPOINTER", _BACKEND_SQLITE).lower()


def _sqlite_path() -> str:
    return os.environ.get("LANGGRAPH_SQLITE_PATH", "./graph.sqlite")


# ---------------------------------------------------------------------------
# Sync factory — for CLI / tests
# ---------------------------------------------------------------------------


def build_checkpointer() -> tuple[object, _Teardown]:
    """Return ``(saver, teardown)`` for the configured backend.

    The ``teardown`` callable closes the underlying connection; invoke it
    from the caller's ``finally`` block.

    Raises
    ------
    ValueError
        If ``LANGGRAPH_CHECKPOINTER`` is set to an unrecognised value.
    """
    _ensure_safe_msgpack()
    backend = _backend()

    if backend == _BACKEND_MEMORY:
        return InMemorySaver(), lambda: None

    if backend == _BACKEND_SQLITE:
        db_path = _sqlite_path()
        logger.info("Building SQLite checkpointer at %s", db_path)
        cm = SqliteSaver.from_conn_string(db_path)
        saver = cm.__enter__()

        def _teardown() -> None:
            logger.info("Closing SQLite checkpointer connection (%s)", db_path)
            cm.__exit__(None, None, None)

        return saver, _teardown

    raise ValueError(
        f"Unrecognised LANGGRAPH_CHECKPOINTER value: {backend!r}. "
        f"Expected one of: {_BACKEND_SQLITE!r}, {_BACKEND_MEMORY!r}."
    )


# ---------------------------------------------------------------------------
# Async factory — for FastAPI lifespan
# ---------------------------------------------------------------------------


async def build_async_checkpointer() -> tuple[object, _AsyncTeardown]:
    """Return ``(saver, async_teardown)`` for the configured backend (async).

    The sync ``SqliteSaver`` does not implement ``aget_tuple``, so the
    async ``graph.ainvoke(...)`` in the /extract endpoint would fail on
    the first checkpoint read against it.  ``AsyncSqliteSaver`` from the
    ``aio`` submodule is the documented async-compatible variant
    (docs.langchain.com/oss/python/langgraph/add-memory).

    Raises
    ------
    ValueError
        If ``LANGGRAPH_CHECKPOINTER`` is set to an unrecognised value.
    """
    _ensure_safe_msgpack()
    backend = _backend()

    if backend == _BACKEND_MEMORY:

        async def _noop() -> None:
            return None

        return InMemorySaver(), _noop

    if backend == _BACKEND_SQLITE:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = _sqlite_path()
        logger.info("Building async SQLite checkpointer at %s", db_path)
        cm = AsyncSqliteSaver.from_conn_string(db_path)
        sqlite_saver = await cm.__aenter__()

        async def _teardown() -> None:
            logger.info("Closing async SQLite checkpointer connection (%s)", db_path)
            await cm.__aexit__(None, None, None)

        return sqlite_saver, _teardown

    raise ValueError(
        f"Unrecognised LANGGRAPH_CHECKPOINTER value: {backend!r}. "
        f"Expected one of: {_BACKEND_SQLITE!r}, {_BACKEND_MEMORY!r}."
    )

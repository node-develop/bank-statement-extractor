"""POST /extract/stream — single-pass SSE extraction endpoint.

Mirrors the validation logic of POST /extract (size, content-type, sha256,
temp-file lifecycle), then opens a ``StreamingResponse`` over
``src.api.streaming.stream_graph_events`` so the graph runs exactly once
and SSE events flow to the client as they happen.

The original POST /extract (JSON) endpoint stays for tests, the held-out
fixture runner, and as a degradation fallback for the frontend.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from src.api.logging import get_logger
from src.api.streaming import stream_graph_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)

router = APIRouter()

_MAX_PDF_BYTES = 80 * 1024 * 1024  # 80 MB (Ixonia Binder2 is ~54 MB)
_MAX_OCR_BYTES = 5 * 1024 * 1024  # 5 MB
_PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


def _delete_file(path: str) -> None:
    """Background task: remove a temporary file after the response is sent."""
    try:
        os.unlink(path)
    except OSError as exc:
        logger.warning("extract_stream: could not delete temp file %s: %s", path, exc)


@router.post("/extract/stream")
async def extract_stream(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Bank-statement PDF (<= 80 MB)")],
    ocr_text: Annotated[
        UploadFile | None,
        File(description="Optional companion OCR text file (<= 5 MB)"),
    ] = None,
) -> StreamingResponse:
    """Stream extraction progress + final ExtractResult as SSE.

    Validates size and content-type, persists the upload to a temporary file,
    then opens a ``StreamingResponse`` over ``stream_graph_events`` so the
    graph runs exactly once and progress events flow to the client as they
    happen.  Each SSE frame is ``data: {json}\\n\\n``.

    The temporary file(s) are deleted after the response is sent via a
    ``BackgroundTask`` so the graph can read them synchronously during
    invocation (SKILL.md pattern).
    """
    # ------------------------------------------------------------------
    # Content-type guard (415)
    # ------------------------------------------------------------------
    if file.content_type not in _PDF_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type: {file.content_type!r}. "
            "Only application/pdf is accepted.",
        )

    # ------------------------------------------------------------------
    # Read bytes — size check (413)
    # ------------------------------------------------------------------
    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum upload size of {_MAX_PDF_BYTES} bytes "
            f"({len(pdf_bytes)} received).",
        )

    # ------------------------------------------------------------------
    # SHA-256 for LangSmith metadata + idempotent cache key (CLAUDE.md rule 3)
    # ------------------------------------------------------------------
    digest = sha256(pdf_bytes).hexdigest()

    # ------------------------------------------------------------------
    # Persist PDF to a named temp file so the graph can open it by path
    # ------------------------------------------------------------------
    pdf_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        pdf_tmp.write(pdf_bytes)
        pdf_tmp.flush()
    finally:
        pdf_tmp.close()
    pdf_path = pdf_tmp.name
    background_tasks.add_task(_delete_file, pdf_path)

    # ------------------------------------------------------------------
    # Optional OCR text companion
    # ------------------------------------------------------------------
    txt_path: str | None = None
    if ocr_text is not None:
        ocr_bytes = await ocr_text.read()
        if len(ocr_bytes) > _MAX_OCR_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"OCR text file exceeds maximum size of {_MAX_OCR_BYTES} bytes "
                f"({len(ocr_bytes)} received).",
            )
        ocr_tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        try:
            ocr_tmp.write(ocr_bytes)
            ocr_tmp.flush()
        finally:
            ocr_tmp.close()
        txt_path = ocr_tmp.name
        background_tasks.add_task(_delete_file, txt_path)

    # ------------------------------------------------------------------
    # Build initial graph state (must match GraphState keys — state.py)
    # ------------------------------------------------------------------
    thread_id = str(uuid.uuid4())
    initial_state: dict[str, Any] = {
        "pdf_path": pdf_path,
        "txt_path": txt_path,
        "layouts": [],
        "accounts": [],
        "summaries": [],
        "transactions": [],
        "reconciliations": [],
        "verifier_reports": [],
        "retry_count": 0,
        "errors": [],
        "notes": [],
        # Phase 3 — cumulative LLM cost (operator.add reducer in GraphState).
        # Must be initialised here or the first node addition raises.
        "cumulative_cost_usd": Decimal("0"),
    }
    # LangSmith metadata per CLAUDE.md "LangSmith" conventions.
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"unknown:{digest[:8]}",
        "tags": ["extract", "stream"],
        "metadata": {"statement_hash": digest},
        "recursion_limit": 50,
    }

    # ------------------------------------------------------------------
    # Open the graph and stream events
    # ------------------------------------------------------------------
    graph = request.app.state.graph
    logger.info(
        "extract_stream: starting thread_id=%s sha256=%s…",
        thread_id,
        digest[:16],
    )

    async def event_source() -> AsyncIterator[bytes]:
        try:
            async for payload in stream_graph_events(graph, initial_state, config):
                yield f"data: {json.dumps(payload, default=str)}\n\n".encode()
        except asyncio.CancelledError:
            logger.info("extract_stream: client disconnected thread_id=%s", thread_id)
            raise

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

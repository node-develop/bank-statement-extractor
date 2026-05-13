"""POST /extract — multipart PDF upload endpoint.

Contract
--------
- ``file``: required ``UploadFile`` (application/pdf or application/x-pdf, ≤ 25 MB).
- ``ocr_text``: optional ``UploadFile`` (text/plain, ≤ 5 MB).
- Returns ``ExtractResult`` JSON on success (HTTP 200).
- 413 when the PDF body exceeds 25 MB.
- 415 when the content-type is not a PDF MIME type.
- 422 when the graph raises ``RuntimeError("ingest: PDF unreadable …")``.
- 500 for all other unhandled exceptions (FastAPI default handler).

No business logic lives here (CLAUDE.md rule 4). The router translates
HTTP → ``graph.ainvoke`` → HTTP and nothing else.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from src.api.logging import get_logger
from src.models import (
    ExtractResult,
    PeriodResult,
    Reconciliation,
)

logger = get_logger(__name__)

router = APIRouter()


def _build_partial_periods_on_pause(
    state: dict[str, Any],
) -> list[PeriodResult]:
    """Assemble PeriodResult objects from state when the graph paused at
    ``await_review`` (rule 12 — surface what we have, never silently empty).

    Runs the pure-Python ``reconcile`` node on the partial state so each
    PeriodResult carries the real Reconciliation (reconciled=True with
    delta=0 when counts and totals match, reconciled=False with specific
    notes when they don't).  Previously every period was stamped
    ``reconciled=False`` regardless — the frontend rendered all 10 chunks
    in the ReviewModal even when only one chunk had verifier suspects.
    """
    from src.nodes.reconcile import reconcile as reconcile_node

    chunks = state.get("period_chunks", []) or []
    accounts = {a.chunk_id: a for a in state.get("accounts", []) or []}
    summaries = {s.chunk_id: s for s in state.get("summaries", []) or []}
    layouts = {la.chunk_id: la for la in state.get("layouts", []) or []}
    verifier_reports = {v.chunk_id: v for v in state.get("verifier_reports", []) or []}
    txs_by_chunk: dict[str, list[Any]] = {}
    for t in state.get("transactions", []) or []:
        txs_by_chunk.setdefault(t.chunk_id, []).append(t)

    # Run the deterministic reconcile node on the partial state to compute
    # per-chunk Reconciliation. reconcile_node returns {"reconciliations": [...]}.
    rec_state = {
        "period_chunks": chunks,
        "summaries": list(state.get("summaries", []) or []),
        "transactions": list(state.get("transactions", []) or []),
    }
    rec_delta = reconcile_node(rec_state)  # type: ignore[arg-type]
    recs_by_id: dict[str, Reconciliation] = {
        r.chunk_id: r for r in rec_delta.get("reconciliations", [])
    }

    out: list[PeriodResult] = []
    for chunk in chunks:
        cid = chunk.chunk_id
        if cid not in accounts or cid not in summaries:
            continue
        layout_label = layouts.get(cid)
        layout_str = layout_label.label if layout_label is not None else "unknown"
        out.append(
            PeriodResult(
                chunk_id=cid,
                account=accounts[cid],
                summary=summaries[cid],
                transactions=txs_by_chunk.get(cid, []),
                layout=layout_str,
                reconciliation=recs_by_id[cid],
                verifier=verifier_reports.get(cid),
            )
        )
    return out


_MAX_PDF_BYTES = 80 * 1024 * 1024  # 80 MB (Ixonia Binder2 is ~54 MB)
_MAX_OCR_BYTES = 5 * 1024 * 1024  # 5 MB
_PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


def _delete_file(path: str) -> None:
    """Background task: remove a temporary file after the response is sent."""
    try:
        os.unlink(path)
    except OSError as exc:
        logger.warning("Could not delete temp file %s: %s", path, exc)


@router.post("/extract", response_model=ExtractResult)
async def extract(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Bank statement PDF (≤ 25 MB)")],
    ocr_text: Annotated[
        UploadFile | None,
        File(description="Optional companion OCR text file (≤ 5 MB)"),
    ] = None,
) -> ExtractResult:
    """Extract structured data from a bank-statement PDF.

    Validates size and content-type, persists the upload to a temporary
    file, invokes the LangGraph extraction pipeline, and returns the
    assembled ``ExtractResult``.

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
    initial_state: dict[str, object] = {
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
    # `bank_slug` and `statement_pages` are NOT known at the API boundary —
    # they emerge after `classify_layout` and `ingest` run inside the graph.
    # M3 will propagate them back into the run tags via a finalize hook.
    config: dict[str, object] = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"unknown:{digest[:8]}",
        "tags": ["extract"],
        "metadata": {"statement_hash": digest},
        "recursion_limit": 50,
    }

    # ------------------------------------------------------------------
    # Invoke the compiled graph (stored on app.state by lifespan)
    # ------------------------------------------------------------------
    graph = request.app.state.graph
    logger.info("extract: invoking graph thread_id=%s sha256=%s…", thread_id, digest[:16])

    try:
        # The lifespan wires an Async{Postgres,Sqlite}Saver into the graph
        # (see src/graph/checkpointer.py:build_async_checkpointer), so
        # ainvoke() can issue real await calls on the checkpointer.
        result_state: dict[str, object] = await graph.ainvoke(initial_state, config=config)
    except RuntimeError as exc:
        if "ingest: PDF unreadable" in str(exc):
            logger.warning("extract: PDF unreadable sha256=%s error=%s", digest[:16], exc)
            return JSONResponse(  # type: ignore[return-value]
                status_code=422,
                content={"error": "pdf_unreadable", "detail": str(exc)},
            )
        raise

    # Phase 4 — detect await_review pause: when the graph hit interrupt(),
    # 'final' is absent and '__interrupt__' carries the suspect payload.
    # Insert a pending_reviews row and return a partial ExtractResult with
    # pending_review set so the frontend can render the modal.
    if "final" not in result_state and "__interrupt__" in result_state:
        from uuid import uuid4

        from src.api import reviews as reviews_db
        from src.models import PendingReview

        # interrupts is list[Interrupt(value=...)]; take the first.
        interrupts: Any = result_state.get("__interrupt__", [])
        payload: dict[str, Any] = (
            interrupts[0].value if interrupts and hasattr(interrupts[0], "value") else {}
        )
        suspect_count = len(payload.get("suspects", []))
        reason = payload.get("reason", "suspects_exceeded")
        extraction_id = str(uuid4())
        reviews_db.insert_pending(
            extraction_id=extraction_id,
            thread_id=thread_id,
            statement_sha256=digest,
            suspect_count=suspect_count,
            reason=reason,
            review_payload=payload,
        )
        logger.info(
            "extract: paused at await_review thread_id=%s extraction_id=%s reason=%s suspects=%d",
            thread_id,
            extraction_id,
            reason,
            suspect_count,
        )
        raw_errors = result_state.get("errors", [])
        errors_list: list[str] = list(raw_errors) if isinstance(raw_errors, list) else []
        raw_notes = result_state.get("notes", [])
        notes_list: list[str] = list(raw_notes) if isinstance(raw_notes, list) else []
        partial_periods = _build_partial_periods_on_pause(result_state)
        return ExtractResult(
            periods=partial_periods,
            statement_sha256=digest,
            errors=errors_list,
            notes=notes_list,
            pending_review=PendingReview(
                extraction_id=extraction_id,
                reason=reason,
                suspect_count=suspect_count,
            ),
        )

    extract_result: ExtractResult = result_state["final"]  # type: ignore[assignment]
    logger.info(
        "extract: done thread_id=%s periods=%d reconciled=%s",
        thread_id,
        len(extract_result.periods),
        all(p.reconciliation.reconciled for p in extract_result.periods),
    )
    return extract_result

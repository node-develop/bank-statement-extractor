"""``apply_human_corrections`` node — re-dispatch extract_transactions per
chunk that has corrections, with the corrections injected as a prompt hint.

The hint MUST be injected into BOTH ``pdf_text`` AND ``ocr_slice`` because
``src/nodes/extract_transactions.py`` prefers ``pdf_text`` and only falls
back to ``ocr_slice`` when ``pdf_text`` is empty.

Returns ``list[Send]`` consumed by the conditional edge in builder.py;
an empty list short-circuits to finalize.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.types import Send

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph

if TYPE_CHECKING:
    from src.models import PeriodChunk

logger = get_logger(__name__)


def _format_correction_hint(corrections: list[dict[str, Any]]) -> str:
    """Build a prompt-prefix block from row-level corrections."""
    lines = ["## Human corrections (treat as ground truth; do not contradict)"]
    for c in corrections:
        action = c.get("action", "?")
        row_index = c.get("row_index", "?")
        fields = c.get("fields", {})
        if action == "edit":
            lines.append(f"- row {row_index}: edit fields = {fields}")
        elif action == "insert":
            lines.append(f"- INSERT at row {row_index}: {fields}")
        elif action == "delete":
            lines.append(f"- DELETE row {row_index}")
        else:
            lines.append(f"- row {row_index}: action={action!r} fields={fields}")
    lines.append("")
    lines.append("## Statement chunk")
    lines.append("")
    return "\n".join(lines) + "\n"


def apply_human_corrections(state: GraphState) -> list[Send]:
    """Re-run ``extract_transactions`` for each chunk with human corrections.

    Reads ``state['human_corrections']`` (list of dict-shaped corrections;
    runtime type is ``list[TransactionCorrection]`` but we accept dicts
    too for forward-compat).
    """
    raw: Any = state.get("human_corrections", []) or []
    if not raw:
        logger.info("apply_human_corrections: no corrections — skipping re-extraction")
        return []

    # Normalise to dicts so we don't depend on TransactionCorrection import here.
    corrections: list[dict[str, Any]] = [c if isinstance(c, dict) else c.model_dump() for c in raw]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for c in corrections:
        cid = c.get("chunk_id")
        if not isinstance(cid, str):
            continue
        grouped.setdefault(cid, []).append(c)

    chunks: list[PeriodChunk] = state.get("period_chunks", [])
    sends: list[Send] = []
    for chunk_id, chunk_corrections in grouped.items():
        chunk = next((c for c in chunks if c.chunk_id == chunk_id), None)
        if chunk is None:
            logger.warning(
                "apply_human_corrections: chunk_id=%r not in period_chunks — skipping",
                chunk_id,
            )
            continue
        hint_block = _format_correction_hint(chunk_corrections)
        annotated = chunk.model_copy(
            update={
                "pdf_text": hint_block + chunk.pdf_text,
                "ocr_slice": (hint_block + chunk.ocr_slice)
                if chunk.ocr_slice is not None
                else None,
            }
        )
        sends.append(Send("extract_transactions", annotated))
        logger.info(
            "apply_human_corrections: dispatched re-extract for chunk_id=%r (%d corrections)",
            chunk_id,
            len(chunk_corrections),
        )
    return sends

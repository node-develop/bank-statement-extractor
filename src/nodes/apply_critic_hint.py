"""``apply_critic_hint`` node — re-dispatch ONE extractor for ONE chunk.

Phase 3 (PRD §4.2.2) — resolves critic GAP-F.

After the ``critic`` node emits a ``CriticHint`` into ``state["pending_hint"]``,
this node turns that hint into a list of ``Send`` objects that re-run exactly
one extractor for exactly one chunk.  The critic's natural-language hint is
prepended to both ``pdf_text`` and ``ocr_slice`` so the extractor sees it
regardless of which text source it prefers.

The returned ``list[Send]`` is consumed by ``add_conditional_edges`` in
``builder.py``; an empty list short-circuits back to ``merge_state`` with
no re-extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.types import Send

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph

if TYPE_CHECKING:
    from src.models import PeriodChunk

logger = get_logger(__name__)


def apply_critic_hint(state: GraphState) -> list[Send]:
    """Re-run ONE extractor for ONE chunk based on ``state['pending_hint']``.

    Parameters
    ----------
    state:
        Full ``GraphState`` after ``critic`` has set ``pending_hint``.

    Returns
    -------
    list[Send]
        Exactly one ``Send`` targeting the extractor named in the hint, or
        an empty list when the hint is absent or the chunk_id is unknown.
        An empty list causes LangGraph to skip re-extraction and proceed to
        ``merge_state`` directly.
    """
    hint: Any = state.get("pending_hint")
    if hint is None:
        logger.warning("apply_critic_hint: pending_hint is absent — skipping re-extraction")
        return []

    chunk_id: str = hint.chunk_id
    extractor: str = hint.extractor

    chunks: list[PeriodChunk] = state.get("period_chunks", [])
    target = next((c for c in chunks if c.chunk_id == chunk_id), None)
    if target is None:
        logger.warning(
            "apply_critic_hint: chunk_id=%r not found in period_chunks — skipping",
            chunk_id,
        )
        return []

    # Prepend the critic's hint to BOTH pdf_text and ocr_slice so the extractor
    # sees it regardless of which source it prefers (same dual-injection rule as
    # apply_human_corrections per PRD §5.5 Finding 5).
    hint_block = (
        "## Critic hint (treat as ground truth; do not contradict)\n"
        f"- {hint.hint}\n\n"
        "## Statement chunk\n\n"
    )
    annotated = target.model_copy(
        update={
            "pdf_text": hint_block + target.pdf_text,
            "ocr_slice": (hint_block + target.ocr_slice) if target.ocr_slice is not None else None,
        }
    )

    logger.info(
        "apply_critic_hint: dispatching Send(%r, chunk_id=%r) with hint prepended",
        extractor,
        chunk_id,
    )
    return [Send(extractor, annotated)]

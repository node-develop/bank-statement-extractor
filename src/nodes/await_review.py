"""``await_review`` graph node — pause via LangGraph ``interrupt()`` for HITL.

Phase 3 (PRD §5.4) — routes here from ``route_after_verifier`` when:
- ``cumulative_cost_usd >= HARD_COST_CAP_USD``, OR
- ``total_suspects > 3``, OR
- ``retry_count >= 2``

Layer boundary (per PRD §5.4 / critic Finding 8): this node does NOT write to
``reviews.sqlite`` directly.  The API layer (POST /extract handler) detects
the interrupt via ``result["__interrupt__"]`` on the graph response and inserts
the ``pending_reviews`` row.  This keeps ``src/nodes/`` free of ``src/api/``
imports.

``reason`` is re-derived inline from the same conditions ``route_after_verifier``
used — no extra ``await_reason`` state key needed (PRD GAP-D resolution).
"""

from __future__ import annotations

from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph

logger = get_logger(__name__)


def _build_partial_periods(state: GraphState) -> list[dict[str, Any]]:
    """Assemble a best-effort per-chunk summary for the human reviewer."""
    chunks = state.get("period_chunks", [])
    accounts = {a.chunk_id: a for a in state.get("accounts", [])}
    summaries = {s.chunk_id: s for s in state.get("summaries", [])}
    txs_by: dict[str, list[Any]] = {}
    for t in state.get("transactions", []):
        txs_by.setdefault(t.chunk_id, []).append(t)
    out: list[dict[str, Any]] = []
    for c in chunks:
        cid = c.chunk_id
        out.append(
            {
                "chunk_id": cid,
                "account": accounts[cid].model_dump() if cid in accounts else None,
                "summary": summaries[cid].model_dump() if cid in summaries else None,
                "tx_count": len(txs_by.get(cid, [])),
            }
        )
    return out


def await_review(state: GraphState) -> dict[str, Any]:
    """Pause the graph; surface suspects via ``interrupt()``; resume on POST /review.

    Parameters
    ----------
    state:
        Full ``GraphState`` at the point where human review is required.

    Returns
    -------
    dict
        State delta containing ``human_corrections``, ``force_resume``,
        ``pending_review``, and ``review_payload`` — populated from the
        ``Command(resume=...)`` response returned by ``interrupt()``.

    Notes
    -----
    The lazy import of ``interrupt`` inside the function body keeps test-time
    import cheap and avoids pulling LangGraph into every import chain.
    """
    from decimal import Decimal as _D  # noqa: N814 — local alias avoids shadowing in narrow scope

    from langgraph.types import interrupt

    from src.api.pricing import HARD_COST_CAP_USD

    reports = state.get("verifier_reports", [])
    total_suspects = sum(len(r.suspects) for r in reports)
    retry = state.get("retry_count", 0)
    cost_capped = state.get("cumulative_cost_usd", _D("0")) >= HARD_COST_CAP_USD

    if cost_capped:
        reason = "cost_ceiling_exceeded"
    elif retry >= 2:
        reason = "retry_exhausted"
    else:
        reason = "suspects_exceeded"

    payload: dict[str, Any] = {
        "suspects": [s.model_dump() for r in reports for s in r.suspects],
        "reason": reason,
        "partial_periods": _build_partial_periods(state),
    }

    logger.info(
        "await_review: pausing graph — reason=%r total_suspects=%d retry=%d cost_capped=%s",
        reason,
        total_suspects,
        retry,
        cost_capped,
    )

    response: Any = interrupt(payload)

    # On resume, response is a dict {corrections, force} from POST /review/{id}.
    corrections: list[Any] = []
    force: bool = False
    if isinstance(response, dict):
        corrections = response.get("corrections", [])
        force = bool(response.get("force", False))

    return {
        "human_corrections": corrections,
        "force_resume": force,
        "pending_review": True,
        "review_payload": payload,
    }

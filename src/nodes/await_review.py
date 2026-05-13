"""``await_review`` graph node — pause via LangGraph ``interrupt()`` for HITL.

Routes here from ``route_after_verifier`` when:
- ``cumulative_cost_usd >= HARD_COST_CAP_USD``, OR
- ``total_suspects > 3``, OR
- ``retry_count >= 2``

Layer boundary: this node does NOT write to ``reviews.sqlite`` directly.  The
API layer (POST /extract handler) detects the interrupt via
``result["__interrupt__"]`` on the graph response and inserts the
``pending_reviews`` row.  This keeps ``src/nodes/`` free of ``src/api/``
imports.

``reason`` is re-derived inline from the same conditions ``route_after_verifier``
used — no extra ``await_reason`` state key needed.
"""

from __future__ import annotations

from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph

logger = get_logger(__name__)


def _build_partial_periods(state: GraphState) -> list[dict[str, Any]]:
    """Assemble a best-effort per-chunk summary for the human reviewer."""
    # On the FIRST pass through await_review, state values are Pydantic
    # models (Account, Summary, Transaction, …). When the graph resumes
    # after POST /review/{id}, LangGraph rehydrates state from the
    # checkpointer; depending on the codec, some fields come back as
    # plain dicts. Use a defensive helper that handles both shapes.
    chunks = state.get("period_chunks", [])
    accounts = {_get_chunk_id(a): a for a in state.get("accounts", [])}
    summaries = {_get_chunk_id(s): s for s in state.get("summaries", [])}
    txs_by: dict[str, list[Any]] = {}
    for t in state.get("transactions", []):
        txs_by.setdefault(_get_chunk_id(t), []).append(t)
    out: list[dict[str, Any]] = []
    for c in chunks:
        cid = _get_chunk_id(c)
        out.append(
            {
                "chunk_id": cid,
                "account": _to_dict(accounts[cid]) if cid in accounts else None,
                "summary": _to_dict(summaries[cid]) if cid in summaries else None,
                "tx_count": len(txs_by.get(cid, [])),
            }
        )
    return out


def _to_dict(obj: Any) -> dict[str, Any] | None:
    """Coerce a pydantic model OR plain dict to a dict.

    Required because LangGraph state rehydration can return either shape
    depending on the checkpointer codec — see comments in _build_partial_periods.
    """
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        result: dict[str, Any] = obj.model_dump()
        return result
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"_to_dict: cannot coerce {type(obj).__name__} to dict")


def _get_chunk_id(obj: Any) -> str:
    """Pull `chunk_id` from a pydantic model OR plain dict."""
    if hasattr(obj, "chunk_id"):
        return str(obj.chunk_id)
    if isinstance(obj, dict):
        return str(obj.get("chunk_id", ""))
    raise TypeError(f"_get_chunk_id: cannot read chunk_id from {type(obj).__name__}")


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

    def _suspects_of(report: Any) -> list[Any]:
        """Suspects attribute may be on a pydantic VerifierReport or a dict."""
        if hasattr(report, "suspects"):
            return list(report.suspects)
        if isinstance(report, dict):
            return list(report.get("suspects") or [])
        return []

    flat_suspects = [s for r in reports for s in _suspects_of(r)]
    total_suspects = len(flat_suspects)
    retry = state.get("retry_count", 0)
    cost_capped = state.get("cumulative_cost_usd", _D("0")) >= HARD_COST_CAP_USD

    if cost_capped:
        reason = "cost_ceiling_exceeded"
    elif retry >= 2:
        reason = "retry_exhausted"
    else:
        reason = "suspects_exceeded"

    # Suspects can be pydantic VerifierSuspect instances OR plain dicts
    # depending on whether this is the first await_review pass or a resume.
    # _to_dict handles both. (Filter Nones in case _to_dict returns None.)
    payload: dict[str, Any] = {
        "suspects": [d for s in flat_suspects if (d := _to_dict(s)) is not None],
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

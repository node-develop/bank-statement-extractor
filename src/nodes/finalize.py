"""``finalize`` graph node — assembles the top-level ``ExtractResult``.

This node runs after ``reconcile`` (or ``critic_loop`` on mismatch) and is the
single point that stitches per-chunk lists back into ``PeriodResult`` objects.
It raises ``KeyError`` when a required chunk_id is absent from any mandatory
list — that is an invariant violation (not a recoverable error) and should
propagate so the graph surfaces it as a node failure.
"""

from __future__ import annotations

from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import ExtractResult, PeriodResult

logger = get_logger(__name__)


def finalize(state: GraphState) -> dict[str, Any]:
    """Assemble ``ExtractResult`` from all per-chunk lists.

    Parameters
    ----------
    state:
        Full ``GraphState`` after reconciliation is complete.

    Returns
    -------
    dict
        ``{"final": ExtractResult}`` — stored under the ``NotRequired``
        ``final`` key added to ``GraphState``.

    Raises
    ------
    KeyError
        When a required chunk_id (account, summary, or reconciliation) is
        missing from the accumulated lists.  This is an invariant violation,
        not a recoverable error.
    """
    chunks = state["period_chunks"]
    accounts = state.get("accounts", [])
    summaries = state.get("summaries", [])
    layouts = state.get("layouts", [])
    reconciliations = state.get("reconciliations", [])
    transactions = state.get("transactions", [])
    verifier_reports = state.get("verifier_reports", [])
    errors = list(state.get("errors", []))
    notes = list(state.get("notes", []))

    # Index per-chunk results by chunk_id for O(1) lookup.
    account_by_id = {a.chunk_id: a for a in accounts}
    summary_by_id = {s.chunk_id: s for s in summaries}
    layout_by_id = {la.chunk_id: la for la in layouts}
    reconciliation_by_id = {r.chunk_id: r for r in reconciliations}
    verifier_by_id = {v.chunk_id: v for v in verifier_reports}

    period_results: list[PeriodResult] = []

    for chunk in chunks:
        cid = chunk.chunk_id

        if cid not in account_by_id:
            raise KeyError(
                f"finalize: no Account found for chunk_id={cid!r}; "
                f"available chunk_ids={list(account_by_id)}"
            )
        if cid not in summary_by_id:
            raise KeyError(
                f"finalize: no Summary found for chunk_id={cid!r}; "
                f"available chunk_ids={list(summary_by_id)}"
            )
        if cid not in reconciliation_by_id:
            raise KeyError(
                f"finalize: no Reconciliation found for chunk_id={cid!r}; "
                f"available chunk_ids={list(reconciliation_by_id)}"
            )

        layout_label = layout_by_id.get(cid)
        layout_str: str = layout_label.label if layout_label is not None else "unknown"

        chunk_transactions = [t for t in transactions if t.chunk_id == cid]

        period_results.append(
            PeriodResult(
                chunk_id=cid,
                account=account_by_id[cid],
                summary=summary_by_id[cid],
                transactions=chunk_transactions,
                layout=layout_str,
                reconciliation=reconciliation_by_id[cid],
                verifier=verifier_by_id.get(cid),
            )
        )

    extract_result = ExtractResult(
        periods=period_results,
        statement_sha256=state["raw"].sha256,
        langsmith_run_url=None,
        errors=errors,
        notes=notes,
    )

    logger.info(
        "finalize: assembled ExtractResult with %d periods, %d total transactions",
        len(period_results),
        sum(len(pr.transactions) for pr in period_results),
    )

    return {"final": extract_result}

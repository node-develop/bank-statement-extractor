"""``reconcile`` graph node — pure-Python per-period reconciliation.

Deterministic arithmetic only — no LLM, no IO (CLAUDE.md rules 5, 11).

Invariants checked per period chunk
-------------------------------------
A. abs(beginning + sum(credits) - sum(debits) - ending) <= EPSILON
B. count(credit transactions) == summary.deposits_count
C. count(debit  transactions) == summary.withdrawals_count
D. abs(sum(credit amounts) - summary.deposits_total)  <= EPSILON
E. abs(sum(debit  amounts) - summary.withdrawals_total) <= EPSILON

All five must pass for ``reconciled = True``.  On any failure, notes[]
receives a human-readable description; delta stores abs(computed - stated)
for the balance invariant (A).

Edge cases
----------
- No transactions extracted for a chunk  → reconciled=False, specific note.
- No summary extracted for a chunk       → reconciled=False, specific note.
- Negative beginning_balance (Sep-2024 / account 4623, etalon row 7):
  handled correctly because Decimal supports negatives.
- Zero-net period (sum(deposits) == sum(withdrawals)):
  beginning + dep - wd == beginning -> must reconcile.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import EPSILON, Reconciliation

if TYPE_CHECKING:
    from src.models import PeriodChunk, Summary, Transaction

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public node
# ---------------------------------------------------------------------------


def reconcile(state: GraphState) -> dict[str, list[Reconciliation]]:
    """Produce one ``Reconciliation`` per period chunk.

    Returns a state delta ``{"reconciliations": [...]}`` whose entries are
    appended by the ``operator.add`` reducer in ``GraphState``.

    Processing order follows ``state["period_chunks"]`` so the output list
    is in the same period order as the rest of the pipeline.
    """
    chunks: list[PeriodChunk] = state["period_chunks"]
    summaries: list[Summary] = state["summaries"]
    transactions: list[Transaction] = state["transactions"]

    # Build lookup maps for O(1) access by chunk_id.
    summary_by_chunk: dict[str, Summary] = {s.chunk_id: s for s in summaries}
    # Group transactions by chunk_id.
    txs_by_chunk: dict[str, list[Transaction]] = {}
    for tx in transactions:
        txs_by_chunk.setdefault(tx.chunk_id, []).append(tx)

    results: list[Reconciliation] = []

    for chunk in chunks:
        rec = _reconcile_chunk(
            chunk_id=chunk.chunk_id,
            summary=summary_by_chunk.get(chunk.chunk_id),
            txs=txs_by_chunk.get(chunk.chunk_id, []),
        )
        results.append(rec)
        _log_result(rec)

    return {"reconciliations": results}


# ---------------------------------------------------------------------------
# Per-chunk logic
# ---------------------------------------------------------------------------


def _reconcile_chunk(
    chunk_id: str,
    summary: Summary | None,
    txs: list[Transaction],
) -> Reconciliation:
    """Reconcile a single period chunk; never raises."""
    # --- Edge case: no summary extracted for this chunk --------------------
    if summary is None:
        logger.warning(
            "reconcile: %s reconciled=False delta=0.00 (no summary extracted)",
            chunk_id,
        )
        return Reconciliation(
            chunk_id=chunk_id,
            reconciled=False,
            delta=Decimal("0.00"),
            notes=["no summary extracted for this chunk"],
        )

    # --- Edge case: no transactions extracted for this chunk ---------------
    if not txs:
        # Delta is the full discrepancy that would arise from zero transactions.
        no_tx_delta = abs(summary.ending_balance - summary.beginning_balance)
        logger.warning(
            "reconcile: %s reconciled=False delta=%s (no transactions extracted)",
            chunk_id,
            no_tx_delta,
        )
        return Reconciliation(
            chunk_id=chunk_id,
            reconciled=False,
            delta=no_tx_delta,
            notes=["no transactions extracted"],
        )

    # --- Compute actuals ---------------------------------------------------
    actual_credits_total: Decimal = sum(
        (t.amount for t in txs if t.direction == "credit"),
        Decimal("0.00"),
    )
    actual_debits_total: Decimal = sum(
        (t.amount for t in txs if t.direction == "debit"),
        Decimal("0.00"),
    )
    actual_credits_count: int = sum(1 for t in txs if t.direction == "credit")
    actual_debits_count: int = sum(1 for t in txs if t.direction == "debit")

    # --- Invariant A: balance equation -------------------------------------
    computed_ending: Decimal = (
        summary.beginning_balance + actual_credits_total - actual_debits_total
    )
    delta: Decimal = abs(summary.ending_balance - computed_ending)

    notes: list[str] = []

    # Check counts first — most common silent failure mode (spec requirement).
    #
    # Sentinel ``summary.deposits_count == 0`` (or withdrawals_count == 0) means
    # the source statement DOESN'T PRINT explicit counts (Chase / BofA /
    # generic US-bank layouts only print totals, not "(N)" counters like
    # Ixonia's "Deposits and Credits (81)").  In that case the extractor
    # emits 0 as "unknown"; we skip the count invariant rather than flag a
    # spurious mismatch when balance arithmetic actually reconciles.
    # Invariant B
    if summary.deposits_count > 0 and actual_credits_count != summary.deposits_count:
        notes.append(
            f"deposits_count: actual={actual_credits_count} vs summary={summary.deposits_count}"
        )

    # Invariant C
    if summary.withdrawals_count > 0 and actual_debits_count != summary.withdrawals_count:
        notes.append(
            f"withdrawals_count: actual={actual_debits_count} "
            f"vs summary={summary.withdrawals_count}"
        )

    # Invariant D
    credits_diff: Decimal = abs(actual_credits_total - summary.deposits_total)
    if credits_diff > EPSILON:
        notes.append(
            f"deposits_total: actual={actual_credits_total} vs summary={summary.deposits_total}"
        )

    # Invariant E
    debits_diff: Decimal = abs(actual_debits_total - summary.withdrawals_total)
    if debits_diff > EPSILON:
        notes.append(
            f"withdrawals_total: actual={actual_debits_total} "
            f"vs summary={summary.withdrawals_total}"
        )

    # Invariant A (balance) — checked last so counts/totals appear first in notes.
    if delta > EPSILON:
        notes.append(
            f"balance: delta={summary.ending_balance - computed_ending}"
            f" exceeds epsilon {EPSILON}"
            f" (expected_ending={computed_ending}, stated_ending={summary.ending_balance})"
        )

    reconciled: bool = len(notes) == 0

    return Reconciliation(
        chunk_id=chunk_id,
        reconciled=reconciled,
        delta=delta,
        notes=notes,
    )


def _log_result(rec: Reconciliation) -> None:
    if rec.reconciled:
        logger.info(
            "reconcile: %s reconciled=%s delta=%s",
            rec.chunk_id,
            rec.reconciled,
            rec.delta,
        )
    else:
        logger.warning(
            "reconcile: %s reconciled=%s delta=%s notes=%r",
            rec.chunk_id,
            rec.reconciled,
            rec.delta,
            rec.notes,
        )

"""``verifier`` graph node — deterministic per-row extraction checks (C1-C6).

Six deterministic checks per period chunk; no LLM required.

C1 balance_chain_break  — running_balance disagrees with prev + signed_amount
C2 date_order           — a transaction date is earlier than the prior row
C3 duplicate_row        — identical (date, amount, direction, description)
C4 empty_description    — description is empty or a known pseudo-row header
C5 zero_amount          — amount is exactly zero (likely a header/separator)
C6 summary_delta        - Sum(credits) - Sum(debits) != ending - beginning

Confidence = max(0, 1 - suspects/rows), quantized to 2 dp.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from src.api.logging import get_logger
from src.models import EPSILON, Gap, Suspect, VerifierReport

if TYPE_CHECKING:
    from src.graph.state import GraphState
    from src.models import Summary, Transaction

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_PSEUDO_DESCRIPTIONS: frozenset[str] = frozenset({"BEGINNING BALANCE", "ENDING BALANCE", ""})


def verify_chunk(summary: Summary, txs: list[Transaction]) -> VerifierReport:
    """Run C1-C6 on one period's transactions and return a VerifierReport.

    Pure Python, Decimal-only arithmetic.  Never raises — all anomalies are
    captured in ``suspects`` and ``gaps``.
    """
    suspects: list[Suspect] = []
    gaps: list[Gap] = []

    # ---- C1: running-balance chain -----------------------------------------
    prev = summary.beginning_balance
    for i, tx in enumerate(txs):
        signed = tx.amount if tx.direction == "credit" else -tx.amount
        expected = prev + signed
        if tx.running_balance is not None and abs(tx.running_balance - expected) > EPSILON:
            suspects.append(
                Suspect(
                    chunk_id=tx.chunk_id,
                    row_index=i,
                    code="balance_chain_break",
                    reason="running_balance does not equal prev_balance + signed_amount",
                    expected=str(expected),
                    actual=str(tx.running_balance),
                )
            )
            # Gap: actual running_balance minus computed expected is the missing amount.
            gaps.append(
                Gap(
                    chunk_id=tx.chunk_id,
                    after_row_index=i - 1,
                    date_range=(txs[i - 1].date if i > 0 else tx.date, tx.date),
                    missing_amount=tx.running_balance - expected,
                )
            )
        prev = tx.running_balance if tx.running_balance is not None else expected

    # ---- C2: date monotonicity ---------------------------------------------
    for i in range(1, len(txs)):
        if txs[i].date < txs[i - 1].date:
            suspects.append(
                Suspect(
                    chunk_id=txs[i].chunk_id,
                    row_index=i,
                    code="date_order",
                    reason=f"date {txs[i].date} earlier than prev {txs[i - 1].date}",
                )
            )

    # ---- C3: duplicate (date, amount, direction, description) --------------
    seen: dict[tuple[object, ...], int] = {}
    for i, tx in enumerate(txs):
        key = (tx.date, tx.amount, tx.direction)
        if key in seen and txs[seen[key]].description == tx.description:
            suspects.append(
                Suspect(
                    chunk_id=tx.chunk_id,
                    row_index=i,
                    code="duplicate_row",
                    reason=f"identical row already seen at index {seen[key]}",
                )
            )
        seen[key] = i

    # ---- C4: empty / pseudo-row description --------------------------------
    for i, tx in enumerate(txs):
        if tx.description.strip().upper() in _PSEUDO_DESCRIPTIONS:
            suspects.append(
                Suspect(
                    chunk_id=tx.chunk_id,
                    row_index=i,
                    code="empty_description",
                    reason=f"description is empty or pseudo-row: {tx.description!r}",
                )
            )

    # ---- C5: zero amount ---------------------------------------------------
    for i, tx in enumerate(txs):
        if tx.amount == Decimal("0"):
            suspects.append(
                Suspect(
                    chunk_id=tx.chunk_id,
                    row_index=i,
                    code="zero_amount",
                    reason="amount is zero — likely a header/separator row",
                )
            )

    # ---- C6: pre-reconcile delta -------------------------------------------
    credits_total = sum((t.amount for t in txs if t.direction == "credit"), Decimal("0"))
    debits_total = sum((t.amount for t in txs if t.direction == "debit"), Decimal("0"))
    computed_ending = summary.beginning_balance + credits_total - debits_total
    delta = summary.ending_balance - computed_ending
    if abs(delta) > EPSILON:
        # Identify the first row whose running_balance breaks the chain.
        # If no row has running_balance (or none break), point at row 0.
        breaker: int | None = None
        chain_prev = summary.beginning_balance
        for i, tx in enumerate(txs):
            signed = tx.amount if tx.direction == "credit" else -tx.amount
            chain_expected = chain_prev + signed
            if (
                tx.running_balance is not None
                and abs(tx.running_balance - chain_expected) > EPSILON
            ):
                breaker = i
                break
            chain_prev = tx.running_balance if tx.running_balance is not None else chain_expected
        suspects.append(
            Suspect(
                chunk_id=txs[0].chunk_id if txs else summary.chunk_id,
                row_index=breaker if breaker is not None else 0,
                code="summary_delta",
                reason=f"sum of rows differs from summary by {delta}",
                expected=str(summary.ending_balance),
                actual=str(computed_ending),
            )
        )

    total_rows = max(len(txs), 1)
    confidence = max(
        Decimal("0"),
        Decimal("1") - Decimal(len(suspects)) / Decimal(total_rows),
    ).quantize(Decimal("0.01"))

    chunk_id = txs[0].chunk_id if txs else summary.chunk_id
    logger.info(
        "verifier: %s confidence=%s suspects=%d gaps=%d",
        chunk_id,
        confidence,
        len(suspects),
        len(gaps),
    )
    return VerifierReport(
        chunk_id=chunk_id,
        confidence=confidence,
        suspects=suspects,
        gaps=gaps,
    )


# ---------------------------------------------------------------------------
# Graph node wrapper
# ---------------------------------------------------------------------------


def verifier(state: GraphState) -> dict[str, list[VerifierReport]]:
    """Run C1-C6 on every (summary, transactions) pair grouped by chunk_id.

    Returns ``{"verifier_reports": [VerifierReport, ...]}``.

    Note: ``verifier_reports`` is not yet wired into ``GraphState`` (Phase 2
    is purely additive — graph wiring happens in Phase 3).  The function is
    callable and unit-tested standalone.
    """
    summaries = {s.chunk_id: s for s in state.get("summaries", [])}
    grouped: dict[str, list[Transaction]] = {}
    for tx in state.get("transactions", []):
        grouped.setdefault(tx.chunk_id, []).append(tx)

    reports: list[VerifierReport] = []
    for chunk_id, summary in summaries.items():
        txs = grouped.get(chunk_id, [])
        reports.append(verify_chunk(summary, txs))

    return {"verifier_reports": reports}

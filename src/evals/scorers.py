"""Pure-Python scoring logic for the evaluation harness (rule 9).

Compares a ``PeriodResult`` against an etalon dict from
``src/evals/datasets/ixonia.jsonl``.  Returns a ``PeriodScore`` with all
five scoring dimensions (account, summary, tx_count, reconciled, delta).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal  # noqa: TC003 — runtime-required for @dataclass(frozen=True) field type
from typing import TYPE_CHECKING, Any

from src.models import EPSILON

if TYPE_CHECKING:
    from src.models import PeriodResult

__all__ = ["PeriodScore", "score_period"]


@dataclass(frozen=True)
class PeriodScore:
    """Scoring result for one period against its etalon."""

    chunk_id: str
    account_last4_match: bool
    summary_exact_match: bool
    summary_field_diffs: dict[str, tuple[str, str]]
    tx_count_match: bool
    expected_tx_count: int
    actual_tx_count: int
    reconciled_match: bool
    delta_within_epsilon: bool
    delta: Decimal

    @property
    def all_pass(self) -> bool:
        return (
            self.account_last4_match
            and self.summary_exact_match
            and self.tx_count_match
            and self.reconciled_match
            and self.delta_within_epsilon
        )


def score_period(period: PeriodResult, etalon: dict[str, Any]) -> PeriodScore:
    """Compare a ``PeriodResult`` against the etalon dict."""
    account_match = period.account.account_last4 == etalon["account_last4"]

    expected_summary = etalon["summary"]
    actual_summary = period.summary
    diffs: dict[str, tuple[str, str]] = {}

    for field in (
        "beginning_balance",
        "ending_balance",
        "deposits_total",
        "withdrawals_total",
    ):
        expected = str(expected_summary[field])
        actual = str(getattr(actual_summary, field))
        if expected != actual:
            diffs[field] = (expected, actual)

    for field in ("deposits_count", "withdrawals_count"):
        expected = str(expected_summary[field])
        actual = str(getattr(actual_summary, field))
        if expected != actual:
            diffs[field] = (expected, actual)

    expected_tx = int(etalon["tx_count"])
    actual_tx = len(period.transactions)

    delta: Decimal = period.reconciliation.delta

    return PeriodScore(
        chunk_id=period.chunk_id,
        account_last4_match=account_match,
        summary_exact_match=not diffs,
        summary_field_diffs=diffs,
        tx_count_match=actual_tx == expected_tx,
        expected_tx_count=expected_tx,
        actual_tx_count=actual_tx,
        reconciled_match=period.reconciliation.reconciled == bool(etalon["reconciled"]),
        delta_within_epsilon=abs(delta) <= EPSILON,
        delta=delta,
    )

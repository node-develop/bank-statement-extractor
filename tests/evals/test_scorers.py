"""Tests for src/evals/scorers.py (rule 9 — business intent)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.evals.scorers import PeriodScore, score_period
from src.models import (
    Account,
    Period,
    PeriodResult,
    Reconciliation,
    Summary,
    Transaction,
)


def _make_period(
    *,
    chunk_id: str = "period_01",
    account_last4: str = "1664",
    beginning_balance: Decimal = Decimal("597068.70"),
    ending_balance: Decimal = Decimal("509121.59"),
    deposits_total: Decimal = Decimal("1214254.05"),
    deposits_count: int = 81,
    withdrawals_total: Decimal = Decimal("1302201.16"),
    withdrawals_count: int = 111,
    tx_count: int = 192,
    reconciled: bool = True,
    delta: Decimal = Decimal("0.00"),
) -> PeriodResult:
    account = Account(
        chunk_id=chunk_id,
        bank="Ixonia Bank",
        account_last4=account_last4,
        period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
    )
    summary = Summary(
        chunk_id=chunk_id,
        beginning_balance=beginning_balance,
        ending_balance=ending_balance,
        deposits_total=deposits_total,
        deposits_count=deposits_count,
        withdrawals_total=withdrawals_total,
        withdrawals_count=withdrawals_count,
    )
    txs = [
        Transaction(
            chunk_id=chunk_id,
            date=date(2025, 4, 1),
            description=f"tx_{i}",
            amount=Decimal("0.01"),
            direction="credit" if i % 2 == 0 else "debit",
        )
        for i in range(tx_count)
    ]
    return PeriodResult(
        chunk_id=chunk_id,
        account=account,
        summary=summary,
        transactions=txs,
        layout="ixonia_business_basic",
        reconciliation=Reconciliation(
            chunk_id=chunk_id, reconciled=reconciled, delta=delta, notes=[]
        ),
    )


def _etalon() -> dict[str, Any]:
    return {
        "account_last4": "1664",
        "summary": {
            "beginning_balance": "597068.70",
            "ending_balance": "509121.59",
            "deposits_total": "1214254.05",
            "deposits_count": 81,
            "withdrawals_total": "1302201.16",
            "withdrawals_count": 111,
        },
        "tx_count": 192,
        "reconciled": True,
    }


def test_score_period_happy_path() -> None:
    score: PeriodScore = score_period(_make_period(), _etalon())
    assert score.account_last4_match is True
    assert score.summary_exact_match is True
    assert score.summary_field_diffs == {}
    assert score.tx_count_match is True
    assert score.reconciled_match is True
    assert score.delta_within_epsilon is True
    assert score.delta == Decimal("0.00")
    assert score.all_pass is True


def test_score_period_summary_diff() -> None:
    score = score_period(_make_period(deposits_count=80), _etalon())
    assert score.summary_exact_match is False
    assert "deposits_count" in score.summary_field_diffs
    assert score.summary_field_diffs["deposits_count"] == ("81", "80")
    assert score.all_pass is False


def test_score_period_tx_count_diff() -> None:
    score = score_period(_make_period(tx_count=191), _etalon())
    assert score.tx_count_match is False
    assert score.expected_tx_count == 192
    assert score.actual_tx_count == 191
    assert score.all_pass is False


def test_score_period_unreconciled_exceeds_epsilon() -> None:
    score = score_period(_make_period(reconciled=False, delta=Decimal("0.50")), _etalon())
    assert score.reconciled_match is False
    assert score.delta_within_epsilon is False
    assert score.delta == Decimal("0.50")
    assert score.all_pass is False


def test_score_period_account_mismatch() -> None:
    score = score_period(_make_period(account_last4="9999"), _etalon())
    assert score.account_last4_match is False
    assert score.all_pass is False

"""Tests for src/models/__init__.py — invariants and JSON round-trips.

- Decimal fields survive JSON round-trip without precision loss.
- Validators reject obviously-wrong input (negative amount, float for money,
  Period.end < start, malformed account_last4).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.models import (
    EPSILON,
    Account,
    LayoutLabel,
    Period,
    PeriodChunk,
    Reconciliation,
    Summary,
    Transaction,
)

# ---------------------------------------------------------------------------
# EPSILON
# ---------------------------------------------------------------------------


def test_epsilon_is_one_cent() -> None:
    """Reconciliation tolerance is exactly $0.01."""
    assert EPSILON == Decimal("0.01")


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------


def test_period_end_before_start_raises() -> None:
    with pytest.raises(ValidationError):
        Period(start=date(2025, 4, 30), end=date(2025, 4, 1))


def test_period_serializes_dates_as_iso() -> None:
    p = Period(start=date(2025, 4, 1), end=date(2025, 4, 30))
    dumped = p.model_dump(mode="json")
    assert dumped == {"start": "2025-04-01", "end": "2025-04-30"}


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


def test_account_last4_must_be_four_digits() -> None:
    p = Period(start=date(2025, 4, 1), end=date(2025, 4, 30))
    with pytest.raises(ValidationError):
        Account(chunk_id="period_01", bank="Ixonia Bank", account_last4="166", period=p)
    with pytest.raises(ValidationError):
        Account(chunk_id="period_01", bank="Ixonia Bank", account_last4="16645", period=p)
    with pytest.raises(ValidationError):
        Account(chunk_id="period_01", bank="Ixonia Bank", account_last4="166X", period=p)


# ---------------------------------------------------------------------------
# Summary — money invariants
# ---------------------------------------------------------------------------


def _ixonia_apr_2025_summary() -> Summary:
    """Etalon Summary for the Apr 2025 / account 1664 period."""
    return Summary(
        chunk_id="period_01",
        beginning_balance=Decimal("597068.70"),
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )


def test_summary_accepts_float_via_str_coercion() -> None:
    """At the LLM-input boundary, JSON delivers numbers as float — the model
    must accept them and convert via str() to preserve printed precision.

    Internal callers still must not pass float (mypy enforces that on every
    typed signature); this validator only fires when LangChain hands us a
    float-typed value via with_structured_output.
    """
    s = Summary(
        chunk_id="period_01",
        beginning_balance=597068.70,  # type: ignore[arg-type]  # LLM-shape input
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )
    assert s.beginning_balance == Decimal("597068.70")


def test_summary_json_round_trip_preserves_decimal() -> None:
    """JSON round-trip on the etalon Apr 2025 numbers must not lose precision."""
    original = _ixonia_apr_2025_summary()
    serialized = json.loads(original.model_dump_json())

    # Field types in the JSON wire schema: Decimal -> quoted string
    assert serialized["beginning_balance"] == "597068.70"
    assert serialized["ending_balance"] == "509121.59"
    assert serialized["deposits_total"] == "1214254.05"
    assert serialized["withdrawals_total"] == "1302201.16"

    # Parsing the strings back as Decimal yields the originals exactly
    assert Decimal(serialized["beginning_balance"]) == Decimal("597068.70")
    assert Decimal(serialized["ending_balance"]) == Decimal("509121.59")

    # Reconciliation invariant on the round-tripped values:
    # beginning + sum(deposits) - sum(withdrawals) == ending  (delta ~= -87947.11)
    delta = (
        Decimal(serialized["beginning_balance"])
        + Decimal(serialized["deposits_total"])
        - Decimal(serialized["withdrawals_total"])
        - Decimal(serialized["ending_balance"])
    )
    assert abs(delta) < EPSILON, f"reconciliation off by {delta}"


def test_summary_negative_count_rejected() -> None:
    with pytest.raises(ValidationError):
        Summary(
            chunk_id="period_01",
            beginning_balance=Decimal("0"),
            ending_balance=Decimal("0"),
            deposits_total=Decimal("0"),
            deposits_count=-1,
            withdrawals_total=Decimal("0"),
            withdrawals_count=0,
        )


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


def test_transaction_amount_rejects_negative() -> None:
    """Amount must be non-negative; sign is conveyed via ``direction``."""
    with pytest.raises(ValidationError):
        Transaction(
            chunk_id="period_01",
            date=date(2025, 4, 1),
            description="AIRLINEHYD 2759/VENDOR PMT",
            amount=Decimal("-1809.28"),
            direction="credit",
        )


def test_transaction_accepts_float_amount_via_str_coercion() -> None:
    """LLM-side floats are accepted via the same str-coercion contract used
    on Summary fields. mypy still rejects float in internal call sites."""
    t = Transaction(
        chunk_id="period_01",
        date=date(2025, 4, 1),
        description="x",
        amount=1809.28,  # type: ignore[arg-type]  # LLM-shape input
        direction="credit",
    )
    assert t.amount == Decimal("1809.28")


def test_transaction_running_balance_optional() -> None:
    t = Transaction(
        chunk_id="period_01",
        date=date(2025, 4, 1),
        description="x",
        amount=Decimal("1.00"),
        direction="credit",
    )
    assert t.running_balance is None


def test_transaction_json_round_trip() -> None:
    t = Transaction(
        chunk_id="period_01",
        date=date(2025, 4, 1),
        description="AIRLINEHYD 2759/VENDOR PMT",
        amount=Decimal("1809.28"),
        direction="credit",
        running_balance=Decimal("598877.98"),
    )
    payload = json.loads(t.model_dump_json())
    assert payload["date"] == "2025-04-01"
    assert payload["amount"] == "1809.28"
    assert payload["running_balance"] == "598877.98"
    assert payload["direction"] == "credit"


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_reconciliation_round_trip() -> None:
    r = Reconciliation(
        chunk_id="period_01",
        reconciled=True,
        delta=Decimal("0.00"),
        notes=[],
    )
    payload = json.loads(r.model_dump_json())
    assert payload == {
        "chunk_id": "period_01",
        "reconciled": True,
        "delta": "0.00",
        "notes": [],
    }


# ---------------------------------------------------------------------------
# PeriodChunk
# ---------------------------------------------------------------------------


def test_period_chunk_account_hint_validation() -> None:
    # Valid: 4 digits
    PeriodChunk(
        chunk_id="period_01",
        page_range=(1, 9),
        pdf_text="...",
        ocr_slice=None,
        account_hint_last4="1664",
    )
    # Valid: None (Nov 2024 OCR omission case)
    PeriodChunk(
        chunk_id="period_09",
        page_range=(1, 1),
        pdf_text="...",
        ocr_slice=None,
        account_hint_last4=None,
    )
    # Invalid: 3 digits
    with pytest.raises(ValidationError):
        PeriodChunk(
            chunk_id="period_01",
            page_range=(1, 1),
            pdf_text="",
            ocr_slice=None,
            account_hint_last4="166",
        )
    # Invalid: letters
    with pytest.raises(ValidationError):
        PeriodChunk(
            chunk_id="period_01",
            page_range=(1, 1),
            pdf_text="",
            ocr_slice=None,
            account_hint_last4="166A",
        )


# ---------------------------------------------------------------------------
# LayoutLabel
# ---------------------------------------------------------------------------


def test_layout_label_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        LayoutLabel(chunk_id="period_01", label="not_a_valid_layout")  # type: ignore[arg-type]


def test_layout_label_accepts_three_known_values() -> None:
    for label in ("ixonia_business_basic", "generic_us_bank", "unknown"):
        ll = LayoutLabel(chunk_id="period_01", label=label)  # type: ignore[arg-type]
        assert ll.label == label

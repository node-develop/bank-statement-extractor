"""Tests for src/nodes/merge_state.py — business-intent assertions.

merge_state is a no-op pass-through that verifies list counts are balanced.
No LLM; no mocking needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.models import (
    Account,
    LayoutLabel,
    Period,
    PeriodChunk,
    RawStatement,
    Reconciliation,
    Summary,
    Transaction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw() -> RawStatement:
    return RawStatement(pages=["page1"], ocr_text=None, sha256="a" * 64, page_count=1)


def _make_chunk(chunk_id: str, page: int = 1) -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(page, page),
        pdf_text="",
        ocr_slice=None,
    )


def _make_account(chunk_id: str) -> Account:
    return Account(
        chunk_id=chunk_id,
        bank="Ixonia Bank",
        account_last4="1664",
        period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
    )


def _make_summary(chunk_id: str) -> Summary:
    return Summary(
        chunk_id=chunk_id,
        beginning_balance=Decimal("597068.70"),
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )


def _make_layout(chunk_id: str) -> LayoutLabel:
    return LayoutLabel(chunk_id=chunk_id, label="ixonia_business_basic")


def _make_reconciliation(chunk_id: str) -> Reconciliation:
    return Reconciliation(
        chunk_id=chunk_id,
        reconciled=True,
        delta=Decimal("0.00"),
        notes=[],
    )


def _make_transaction(chunk_id: str) -> Transaction:
    return Transaction(
        chunk_id=chunk_id,
        date=date(2025, 4, 1),
        description="VENDOR PMT",
        amount=Decimal("1809.28"),
        direction="credit",
        running_balance=Decimal("598877.98"),
    )


def _make_state(
    chunks: list[PeriodChunk],
    accounts: list[Account],
    summaries: list[Summary],
    layouts: list[LayoutLabel],
    reconciliations: list[Reconciliation] | None = None,
    transactions: list[Transaction] | None = None,
) -> dict:  # type: ignore[type-arg]
    """Build a minimal GraphState-like dict for merge_state tests."""
    return {
        "pdf_path": "/tmp/test.pdf",
        "txt_path": None,
        "raw": _make_raw(),
        "period_chunks": chunks,
        "layouts": layouts,
        "accounts": accounts,
        "summaries": summaries,
        "transactions": transactions or [],
        "reconciliations": reconciliations or [],
        "retry_count": 0,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Test 1 — balanced lists → returns {} (no errors)
# ---------------------------------------------------------------------------


def test_merge_state_balanced_returns_empty() -> None:
    """When all chunk-count lists match len(period_chunks), merge_state returns {}."""
    from src.nodes.merge_state import merge_state

    chunks = [_make_chunk("c1"), _make_chunk("c2")]
    state = _make_state(
        chunks=chunks,
        accounts=[_make_account("c1"), _make_account("c2")],
        summaries=[_make_summary("c1"), _make_summary("c2")],
        layouts=[_make_layout("c1"), _make_layout("c2")],
        transactions=[_make_transaction("c1"), _make_transaction("c2")],
        reconciliations=[_make_reconciliation("c1"), _make_reconciliation("c2")],
    )

    result = merge_state(state)  # type: ignore[arg-type]

    assert result == {}, f"Balanced state must return empty dict, got {result!r}"


# ---------------------------------------------------------------------------
# Test 2 — one missing account entry → returns {"errors": [...]}
# ---------------------------------------------------------------------------


def test_merge_state_missing_account_returns_error() -> None:
    """When accounts list is shorter than period_chunks, an error is returned."""
    from src.nodes.merge_state import merge_state

    chunks = [_make_chunk("c1"), _make_chunk("c2")]
    state = _make_state(
        chunks=chunks,
        # Only one account instead of two — simulates a fan-out branch that failed
        accounts=[_make_account("c1")],
        summaries=[_make_summary("c1"), _make_summary("c2")],
        layouts=[_make_layout("c1"), _make_layout("c2")],
    )

    result = merge_state(state)  # type: ignore[arg-type]

    assert "errors" in result, "Expected errors key when accounts list is shorter"
    errors = result["errors"]
    assert len(errors) >= 1
    # Error message must mention the list name and the expected count
    assert any("accounts" in e for e in errors), f"Error should mention 'accounts', got {errors}"


# ---------------------------------------------------------------------------
# Test 3 — missing layout entry → error mentions 'layouts'
# ---------------------------------------------------------------------------


def test_merge_state_missing_layout_returns_error() -> None:
    """When layouts list is shorter than period_chunks, an error is returned."""
    from src.nodes.merge_state import merge_state

    chunks = [_make_chunk("c1"), _make_chunk("c2"), _make_chunk("c3")]
    state = _make_state(
        chunks=chunks,
        accounts=[_make_account("c1"), _make_account("c2"), _make_account("c3")],
        summaries=[_make_summary("c1"), _make_summary("c2"), _make_summary("c3")],
        # layouts missing c3
        layouts=[_make_layout("c1"), _make_layout("c2")],
    )

    result = merge_state(state)  # type: ignore[arg-type]

    assert "errors" in result
    assert any("layouts" in e for e in result["errors"]), (
        f"Error should mention 'layouts', got {result['errors']}"
    )

"""Tests for src/nodes/finalize.py — business-intent assertions.

finalize assembles ExtractResult from all per-chunk lists. No LLM needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.models import (
    Account,
    ExtractResult,
    LayoutLabel,
    Period,
    PeriodChunk,
    PeriodResult,
    RawStatement,
    Reconciliation,
    Summary,
    Transaction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw(sha256: str = "b" * 64) -> RawStatement:
    return RawStatement(pages=["page1"], ocr_text=None, sha256=sha256, page_count=1)


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


def _make_transaction(chunk_id: str, amount: str = "100.00") -> Transaction:
    return Transaction(
        chunk_id=chunk_id,
        date=date(2025, 4, 1),
        description="VENDOR PMT",
        amount=Decimal(amount),
        direction="credit",
        running_balance=Decimal("598877.98"),
    )


def _make_full_state(
    chunks: list[PeriodChunk],
    extra_transactions: list[Transaction] | None = None,
    sha256: str = "b" * 64,
    errors: list[str] | None = None,
) -> dict:  # type: ignore[type-arg]
    """Build a complete GraphState-like dict for finalize tests.

    Each chunk gets exactly one account, summary, layout, reconciliation, and
    one transaction (plus any extra_transactions provided).
    """
    accounts = [_make_account(c.chunk_id) for c in chunks]
    summaries = [_make_summary(c.chunk_id) for c in chunks]
    layouts = [_make_layout(c.chunk_id) for c in chunks]
    reconciliations = [_make_reconciliation(c.chunk_id) for c in chunks]
    transactions: list[Transaction] = [_make_transaction(c.chunk_id) for c in chunks]
    if extra_transactions:
        transactions.extend(extra_transactions)

    return {
        "pdf_path": "/tmp/test.pdf",
        "txt_path": None,
        "raw": _make_raw(sha256=sha256),
        "period_chunks": chunks,
        "layouts": layouts,
        "accounts": accounts,
        "summaries": summaries,
        "transactions": transactions,
        "reconciliations": reconciliations,
        "retry_count": 0,
        "errors": errors or [],
    }


# ---------------------------------------------------------------------------
# Test 1 — happy path with 10 chunks: ExtractResult has 10 periods
# ---------------------------------------------------------------------------


def test_finalize_ten_chunks_produces_ten_periods() -> None:
    """finalize must produce ExtractResult with exactly len(period_chunks) periods."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk(f"chunk_{i:02d}", page=i) for i in range(1, 11)]
    state = _make_full_state(chunks, sha256="c" * 64)

    result = finalize(state)  # type: ignore[arg-type]

    assert "final" in result
    extract = result["final"]
    assert isinstance(extract, ExtractResult)
    assert len(extract.periods) == 10, f"Expected 10 periods, got {len(extract.periods)}"
    assert extract.statement_sha256 == "c" * 64


def test_finalize_sha256_matches_raw() -> None:
    """ExtractResult.statement_sha256 must equal state['raw'].sha256."""
    from src.nodes.finalize import finalize

    expected_sha = "d" * 64
    chunks = [_make_chunk("only_chunk")]
    state = _make_full_state(chunks, sha256=expected_sha)

    result = finalize(state)  # type: ignore[arg-type]

    assert result["final"].statement_sha256 == expected_sha


def test_finalize_transactions_filtered_by_chunk_id() -> None:
    """Each PeriodResult.transactions must contain only transactions for that chunk_id."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("alpha"), _make_chunk("beta")]
    # Add an extra transaction belonging to 'alpha'
    extra = _make_transaction("alpha", amount="999.00")
    state = _make_full_state(chunks, extra_transactions=[extra])

    result = finalize(state)  # type: ignore[arg-type]

    period_by_id = {p.chunk_id: p for p in result["final"].periods}

    # alpha has the base transaction plus the extra one
    assert len(period_by_id["alpha"].transactions) == 2, (
        f"alpha should have 2 transactions, got {len(period_by_id['alpha'].transactions)}"
    )
    # beta has only its own base transaction
    assert len(period_by_id["beta"].transactions) == 1, (
        f"beta should have 1 transaction, got {len(period_by_id['beta'].transactions)}"
    )
    for tx in period_by_id["alpha"].transactions:
        assert tx.chunk_id == "alpha"
    for tx in period_by_id["beta"].transactions:
        assert tx.chunk_id == "beta"


def test_finalize_period_result_fields_match_input() -> None:
    """PeriodResult fields (account, summary, layout, reconciliation) must match input."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("p01")]
    state = _make_full_state(chunks)

    result = finalize(state)  # type: ignore[arg-type]

    period: PeriodResult = result["final"].periods[0]
    assert period.chunk_id == "p01"
    assert period.account.bank == "Ixonia Bank"
    assert period.account.account_last4 == "1664"
    assert period.summary.deposits_count == 81
    assert period.layout == "ixonia_business_basic"
    assert period.reconciliation.reconciled is True


def test_finalize_errors_propagated() -> None:
    """Errors accumulated in state['errors'] must appear in ExtractResult.errors."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("e01")]
    state = _make_full_state(chunks, errors=["some prior error"])

    result = finalize(state)  # type: ignore[arg-type]

    assert "some prior error" in result["final"].errors


# ---------------------------------------------------------------------------
# Test 2 — missing chunk_id raises KeyError
# ---------------------------------------------------------------------------


def test_finalize_missing_account_chunk_id_raises() -> None:
    """When an account is missing for a chunk_id, finalize must raise KeyError."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("present"), _make_chunk("missing_account")]
    state = _make_full_state(chunks)

    # Remove the account for 'missing_account' from state
    state["accounts"] = [a for a in state["accounts"] if a.chunk_id != "missing_account"]

    with pytest.raises(KeyError, match="missing_account"):
        finalize(state)  # type: ignore[arg-type]


def test_finalize_missing_summary_chunk_id_raises() -> None:
    """When a summary is missing for a chunk_id, finalize must raise KeyError."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("c1"), _make_chunk("c2_no_summary")]
    state = _make_full_state(chunks)

    state["summaries"] = [s for s in state["summaries"] if s.chunk_id != "c2_no_summary"]

    with pytest.raises(KeyError, match="c2_no_summary"):
        finalize(state)  # type: ignore[arg-type]


def test_finalize_missing_reconciliation_chunk_id_raises() -> None:
    """When a reconciliation is missing for a chunk_id, finalize must raise KeyError."""
    from src.nodes.finalize import finalize

    chunks = [_make_chunk("r1"), _make_chunk("r2_no_rec")]
    state = _make_full_state(chunks)

    state["reconciliations"] = [r for r in state["reconciliations"] if r.chunk_id != "r2_no_rec"]

    with pytest.raises(KeyError, match="r2_no_rec"):
        finalize(state)  # type: ignore[arg-type]

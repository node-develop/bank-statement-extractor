"""Tests for src/nodes/reconcile.py — business-intent assertions.

Seven tests covering:
  1. Happy path: Ixonia Apr-2025 etalon.
  2. Off-by-one-cent balance error.
  3. Transaction count mismatch (deposits_count).
  4. Zero-net period: Sep-2024 / account 4623 (etalon row 7).
  5. No transactions for a chunk.
  6. No summary for a chunk.
  7. Decimal precision: no float drift in 1 000-entry sum.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Literal, cast

from src.models import PeriodChunk, Reconciliation, Summary, Transaction

if TYPE_CHECKING:
    from src.graph.state import GraphState

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_SENTINEL_DATE = date(2025, 4, 1)


def _build_synthetic_transactions(
    chunk_id: str,
    direction: Literal["credit", "debit"],
    n: int,
    total: Decimal,
    start_date: date = _SENTINEL_DATE,
) -> list[Transaction]:
    """Build *n* Transactions whose ``amount`` sum equals *total* exactly.

    The first n-1 slices are quantized down (ROUND_DOWN) so the last
    slice absorbs the rounding remainder; the running sum is therefore
    exact to 2 dp.
    """
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    txs: list[Transaction] = []
    accumulated = Decimal("0")
    for i in range(n - 1):
        txs.append(
            Transaction(
                chunk_id=chunk_id,
                date=start_date,
                description=f"synthetic_{direction}_{i}",
                amount=base,
                direction=direction,
            )
        )
        accumulated += base
    last_amount = total - accumulated
    txs.append(
        Transaction(
            chunk_id=chunk_id,
            date=start_date,
            description=f"synthetic_{direction}_{n - 1}",
            amount=last_amount,
            direction=direction,
        )
    )
    return txs


def _make_chunk(chunk_id: str) -> PeriodChunk:
    """Build a minimal PeriodChunk for the given chunk_id."""
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 1),
        pdf_text="",
        ocr_slice=None,
        account_hint_last4=None,
    )


def _make_state(
    *,
    chunks: list[PeriodChunk],
    summaries: list[Summary],
    transactions: list[Transaction],
) -> GraphState:
    """Build a minimal GraphState-shaped dict for reconcile."""
    from src.models import RawStatement

    raw = RawStatement(
        pages=[""],
        ocr_text=None,
        sha256="a" * 64,
        page_count=1,
    )
    return cast(
        "GraphState",
        {
            "pdf_path": "dummy.pdf",
            "txt_path": None,
            "raw": raw,
            "period_chunks": chunks,
            "layouts": [],
            "accounts": [],
            "summaries": summaries,
            "transactions": transactions,
            "reconciliations": [],
            "retry_count": 0,
            "errors": [],
        },
    )


# ---------------------------------------------------------------------------
# Test 1 — happy path: Ixonia Apr-2025 etalon
# ---------------------------------------------------------------------------

# Ixonia Apr-2025 etalon:
#   beginning=597068.70, ending=509121.59
#   deposits_total=1214254.05, deposits_count=81
#   withdrawals_total=1302201.16, withdrawals_count=111
# Check: 597068.70 + 1214254.05 - 1302201.16 = 509121.59  ✓

_APR_CHUNK_ID = "period_01"
_APR_BEGINNING = Decimal("597068.70")
_APR_ENDING = Decimal("509121.59")
_APR_DEP_TOTAL = Decimal("1214254.05")
_APR_DEP_COUNT = 81
_APR_WD_TOTAL = Decimal("1302201.16")
_APR_WD_COUNT = 111


def _apr_summary() -> Summary:
    return Summary(
        chunk_id=_APR_CHUNK_ID,
        beginning_balance=_APR_BEGINNING,
        ending_balance=_APR_ENDING,
        deposits_total=_APR_DEP_TOTAL,
        deposits_count=_APR_DEP_COUNT,
        withdrawals_total=_APR_WD_TOTAL,
        withdrawals_count=_APR_WD_COUNT,
    )


def _apr_transactions(
    override_credits_total: Decimal | None = None,
    override_credits_count: int | None = None,
) -> list[Transaction]:
    credits_total = override_credits_total if override_credits_total is not None else _APR_DEP_TOTAL
    credits_count = override_credits_count if override_credits_count is not None else _APR_DEP_COUNT
    credits = _build_synthetic_transactions(_APR_CHUNK_ID, "credit", credits_count, credits_total)
    debits = _build_synthetic_transactions(_APR_CHUNK_ID, "debit", _APR_WD_COUNT, _APR_WD_TOTAL)
    return credits + debits


def test_reconcile_ixonia_apr_2025() -> None:
    """Happy path: exact etalon numbers must produce reconciled=True, delta=0.00."""
    from src.nodes.reconcile import reconcile

    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[_apr_summary()],
        transactions=_apr_transactions(),
    )
    result = reconcile(state)
    recs: list[Reconciliation] = result["reconciliations"]

    assert len(recs) == 1
    rec = recs[0]
    assert rec.chunk_id == _APR_CHUNK_ID
    assert rec.reconciled is True, f"Expected reconciled=True; notes={rec.notes}"
    assert rec.delta == Decimal("0.00"), f"Expected delta=0.00, got {rec.delta}"
    assert rec.notes == [], f"Expected no notes, got {rec.notes}"


# ---------------------------------------------------------------------------
# Test 2 — off by one cent
# ---------------------------------------------------------------------------


def test_reconcile_off_by_two_cents_fails() -> None:
    """A 2-cent overshoot (clearly exceeds EPSILON=0.01) must flip reconciled=False."""
    from src.nodes.reconcile import reconcile

    # Build transactions with credits summing to deposits_total + 0.02 so the
    # mismatch strictly exceeds EPSILON (0.01 is the tolerance boundary).
    bad_total = _APR_DEP_TOTAL + Decimal("0.02")
    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[_apr_summary()],
        transactions=_apr_transactions(override_credits_total=bad_total),
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is False
    assert rec.delta == Decimal("0.02"), f"Expected delta=0.02, got {rec.delta}"
    # At least one note must mention balance or deposits_total.
    assert any("balance" in n or "deposits_total" in n for n in rec.notes), (
        f"Expected note about balance or deposits_total; notes={rec.notes}"
    )


def test_reconcile_exactly_one_cent_is_within_epsilon() -> None:
    """A 1-cent overshoot equals EPSILON — must still reconcile (boundary check)."""
    from src.nodes.reconcile import reconcile

    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[_apr_summary()],
        transactions=_apr_transactions(
            override_credits_total=_APR_DEP_TOTAL + Decimal("0.01"),
        ),
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is True, (
        f"|delta|=0.01 should reconcile (= EPSILON); got notes={rec.notes}"
    )


# ---------------------------------------------------------------------------
# Test 3 — count mismatch (missing one deposit transaction)
# ---------------------------------------------------------------------------


def test_reconcile_missing_transaction_count() -> None:
    """80 credits vs summary 81 -> reconciled=False, note mentions deposits_count."""
    from src.nodes.reconcile import reconcile

    # Provide 80 credits summing to the correct total (so amounts match, count doesn't).
    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[_apr_summary()],
        transactions=_apr_transactions(override_credits_count=80),
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is False
    assert any("deposits_count" in n for n in rec.notes), (
        f"Expected note about deposits_count; notes={rec.notes}"
    )


# ---------------------------------------------------------------------------
# Test 4 — zero-net period: Sep-2024 / account 4623 (etalon row 7)
# ---------------------------------------------------------------------------

# Etalon:
#   beginning=-4.00, ending=-4.00
#   deposits_total=336565.07, deposits_count=13
#   withdrawals_total=336565.07, withdrawals_count=35
# Check: -4.00 + 336565.07 - 336565.07 = -4.00  ✓

_SEP_4623_CHUNK_ID = "period_07"
_SEP_4623_BEGINNING = Decimal("-4.00")
_SEP_4623_ENDING = Decimal("-4.00")
_SEP_4623_DEP_TOTAL = Decimal("336565.07")
_SEP_4623_DEP_COUNT = 13
_SEP_4623_WD_TOTAL = Decimal("336565.07")
_SEP_4623_WD_COUNT = 35


def test_reconcile_period_7_zero_net() -> None:
    """Zero-net period with negative beginning balance must reconcile (delta=0.00)."""
    from src.nodes.reconcile import reconcile

    summary = Summary(
        chunk_id=_SEP_4623_CHUNK_ID,
        beginning_balance=_SEP_4623_BEGINNING,
        ending_balance=_SEP_4623_ENDING,
        deposits_total=_SEP_4623_DEP_TOTAL,
        deposits_count=_SEP_4623_DEP_COUNT,
        withdrawals_total=_SEP_4623_WD_TOTAL,
        withdrawals_count=_SEP_4623_WD_COUNT,
    )
    credits = _build_synthetic_transactions(
        _SEP_4623_CHUNK_ID, "credit", _SEP_4623_DEP_COUNT, _SEP_4623_DEP_TOTAL
    )
    debits = _build_synthetic_transactions(
        _SEP_4623_CHUNK_ID, "debit", _SEP_4623_WD_COUNT, _SEP_4623_WD_TOTAL
    )

    state = _make_state(
        chunks=[_make_chunk(_SEP_4623_CHUNK_ID)],
        summaries=[summary],
        transactions=credits + debits,
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is True, f"Expected reconciled=True; notes={rec.notes}"
    assert rec.delta == Decimal("0.00"), f"Expected delta=0.00, got {rec.delta}"


# ---------------------------------------------------------------------------
# Test 5 — no transactions for a chunk
# ---------------------------------------------------------------------------


def test_reconcile_no_transactions_for_chunk() -> None:
    """Empty transaction list → reconciled=False, note mentions 'no transactions extracted'."""
    from src.nodes.reconcile import reconcile

    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[_apr_summary()],
        transactions=[],  # deliberately empty
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is False
    assert any("no transactions extracted" in n for n in rec.notes), (
        f"Expected 'no transactions extracted' note; notes={rec.notes}"
    )


# ---------------------------------------------------------------------------
# Test 6 — no summary for a chunk
# ---------------------------------------------------------------------------


def test_reconcile_no_summary_for_chunk() -> None:
    """Period chunk with no matching summary → Reconciliation emitted with reconciled=False."""
    from src.nodes.reconcile import reconcile

    orphan_chunk_id = "period_99"
    state = _make_state(
        chunks=[_make_chunk(orphan_chunk_id)],
        summaries=[],  # no summary for this chunk
        transactions=[],
    )
    result = reconcile(state)
    recs = result["reconciliations"]

    assert len(recs) == 1
    rec = recs[0]
    assert rec.chunk_id == orphan_chunk_id
    assert rec.reconciled is False
    assert any("no summary extracted" in n for n in rec.notes), (
        f"Expected 'no summary extracted' note; notes={rec.notes}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Decimal precision: no float drift
# ---------------------------------------------------------------------------


def test_reconcile_decimal_precision() -> None:
    """1000 x Decimal('0.01') must sum to exactly Decimal('10.00') - no float drift."""
    chunk_id = "period_prec"

    # Build 1000 credit transactions each worth $0.01.
    credits = [
        Transaction(
            chunk_id=chunk_id,
            date=_SENTINEL_DATE,
            description=f"penny_{i}",
            amount=Decimal("0.01"),
            direction="credit",
        )
        for i in range(1000)
    ]

    # Sanity-check the helper sum itself (rule: Decimal-only arithmetic).
    total_from_sum = sum((t.amount for t in credits), Decimal("0"))
    assert total_from_sum == Decimal("10.00"), (
        f"Sum of 1000 x Decimal('0.01') must be Decimal('10.00'), got {total_from_sum}"
    )

    # Also verify reconcile handles it end-to-end.
    from src.nodes.reconcile import reconcile

    summary = Summary(
        chunk_id=chunk_id,
        beginning_balance=Decimal("0.00"),
        ending_balance=Decimal("10.00"),
        deposits_total=Decimal("10.00"),
        deposits_count=1000,
        withdrawals_total=Decimal("0.00"),
        withdrawals_count=0,
    )
    state = _make_state(
        chunks=[_make_chunk(chunk_id)],
        summaries=[summary],
        transactions=credits,
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is True, f"Expected reconciled=True; notes={rec.notes}"
    assert rec.delta == Decimal("0.00")


# ---------------------------------------------------------------------------
# Test: output ordering follows period_chunks order
# ---------------------------------------------------------------------------


def test_reconcile_output_order_follows_chunks() -> None:
    """reconcile() must emit Reconciliation entries in period_chunks order, not summaries order."""
    from src.nodes.reconcile import reconcile

    # Two chunks: id_B declared first in summaries, id_A declared first in chunks.
    id_a, id_b = "period_a", "period_b"

    def _simple_summary(cid: str) -> Summary:
        return Summary(
            chunk_id=cid,
            beginning_balance=Decimal("100.00"),
            ending_balance=Decimal("100.00"),
            deposits_total=Decimal("0.00"),
            deposits_count=0,
            withdrawals_total=Decimal("0.00"),
            withdrawals_count=0,
        )

    state = _make_state(
        chunks=[_make_chunk(id_a), _make_chunk(id_b)],
        summaries=[_simple_summary(id_b), _simple_summary(id_a)],  # reversed order
        transactions=[],  # zero transactions → reconciled=False for both, but order is what we test
    )
    result = reconcile(state)
    recs = result["reconciliations"]

    assert len(recs) == 2
    assert recs[0].chunk_id == id_a, "First entry must match first chunk"
    assert recs[1].chunk_id == id_b, "Second entry must match second chunk"


def test_reconcile_count_sentinel_zero_skips_count_invariant() -> None:
    """summary.deposits_count == 0 means "not printed by source statement"
    (Chase / BofA / generic US-bank layouts).  Reconciler must skip the
    count invariant in that case so balance-perfect statements reconcile.
    """
    from src.nodes.reconcile import reconcile

    # Simulate a Chase-style summary: balance math is exact, but counts are 0.
    summary = Summary(
        chunk_id=_APR_CHUNK_ID,
        beginning_balance=Decimal("48762.34"),
        ending_balance=Decimal("73174.72"),
        deposits_total=Decimal("110850.55"),
        deposits_count=0,  # sentinel: count not printed in source
        withdrawals_total=Decimal("86438.17"),
        withdrawals_count=0,  # sentinel: count not printed
    )
    # 18 transactions split into 8 credits + 10 debits — counts don't match
    # the summary's 0/0 sentinel, but reconciler should not flag.
    credits = _build_synthetic_transactions(
        _APR_CHUNK_ID, "credit", n=8, total=Decimal("110850.55")
    )
    debits = _build_synthetic_transactions(_APR_CHUNK_ID, "debit", n=10, total=Decimal("86438.17"))
    state = _make_state(
        chunks=[_make_chunk(_APR_CHUNK_ID)],
        summaries=[summary],
        transactions=credits + debits,
    )
    result = reconcile(state)
    rec = result["reconciliations"][0]

    assert rec.reconciled is True, (
        f"balance is exact and counts are sentinels — should reconcile; got notes={rec.notes}"
    )
    assert rec.delta == Decimal("0.00")

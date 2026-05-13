"""Tests for src/nodes/verifier.py — deterministic C1-C6 checks.

Eight tests:
  1. Clean chain passes (confidence=1.00, no suspects, no gaps).
  2. Broken running balance → balance_chain_break + gap + summary_delta.
  3. Date inversion → date_order suspect.
  4. Duplicate row → duplicate_row suspect.
  5. Pseudo-row description → empty_description suspect.
  6. Zero amount → zero_amount suspect.
  7. Summary delta with no running_balance → summary_delta at row_index=0.
  8. Confidence formula: N suspects on M rows → 1 - N/M.

All tests use pure-Python synthetic data; no LLM mocks needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.models import Summary, Transaction, VerifierReport
from src.nodes.verifier import verify_chunk

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CHUNK_ID = "period_01"
_BASE_DATE = date(2025, 4, 1)


def _tx(
    *,
    i: int,
    amount: str,
    direction: str = "credit",
    description: str | None = None,
    running_balance: str | None = None,
    tx_date: date | None = None,
) -> Transaction:
    """Build a Transaction with sensible defaults."""
    return Transaction(
        chunk_id=_CHUNK_ID,
        date=tx_date or date(2025, 4, i + 1),
        description=description if description is not None else f"tx_{i}",
        amount=Decimal(amount),
        direction=direction,  # type: ignore[arg-type]
        running_balance=Decimal(running_balance) if running_balance is not None else None,
    )


def _summary(
    *,
    beginning: str = "0.00",
    ending: str | None = None,
    deposits_total: str = "0.00",
    deposits_count: int = 0,
    withdrawals_total: str = "0.00",
    withdrawals_count: int = 0,
) -> Summary:
    computed_end = ending or str(
        Decimal(beginning) + Decimal(deposits_total) - Decimal(withdrawals_total)
    )
    return Summary(
        chunk_id=_CHUNK_ID,
        beginning_balance=Decimal(beginning),
        ending_balance=Decimal(computed_end),
        deposits_total=Decimal(deposits_total),
        deposits_count=deposits_count,
        withdrawals_total=Decimal(withdrawals_total),
        withdrawals_count=withdrawals_count,
    )


# ---------------------------------------------------------------------------
# Test 1 — clean chain
# ---------------------------------------------------------------------------


def test_verifier_clean_chain_passes() -> None:
    """Consistent running_balance + sum matches summary → confidence=1.00, no suspects."""
    # 3 credits: 100, 200, 300 — total 600
    # beginning=1000, ending=1600
    txs = [
        Transaction(
            chunk_id=_CHUNK_ID,
            date=date(2025, 4, 1),
            description="deposit_a",
            amount=Decimal("100.00"),
            direction="credit",
            running_balance=Decimal("1100.00"),
        ),
        Transaction(
            chunk_id=_CHUNK_ID,
            date=date(2025, 4, 2),
            description="deposit_b",
            amount=Decimal("200.00"),
            direction="credit",
            running_balance=Decimal("1300.00"),
        ),
        Transaction(
            chunk_id=_CHUNK_ID,
            date=date(2025, 4, 3),
            description="deposit_c",
            amount=Decimal("300.00"),
            direction="credit",
            running_balance=Decimal("1600.00"),
        ),
    ]
    summary = _summary(
        beginning="1000.00",
        ending="1600.00",
        deposits_total="600.00",
        deposits_count=3,
    )
    report = verify_chunk(summary, txs)

    assert isinstance(report, VerifierReport)
    assert report.confidence == Decimal("1.00")
    assert report.suspects == []
    assert report.gaps == []


# ---------------------------------------------------------------------------
# Test 2 — broken running balance
# ---------------------------------------------------------------------------


def test_verifier_broken_running_balance() -> None:
    """Running balance off by $50 starting row 5 → exactly 1 balance_chain_break + gap.

    All rows from row 5 onwards carry the +$50 shift so the per-row chain
    re-synchronises (each row's stated_rb matches prev+amount), but the
    individual transaction amounts still sum correctly to the summary
    deposits_total — so C6 does NOT fire.  Only C1 fires once at row 4.
    """
    beginning = Decimal("1000.00")
    amount = Decimal("10.00")
    txs: list[Transaction] = []
    balance = beginning
    for i in range(8):
        balance += amount
        # Apply the $50 shift to row 4 AND all subsequent rows so the chain
        # re-syncs after the break — only the transition at row 4 is detected.
        stated_rb = balance + (Decimal("50.00") if i >= 4 else Decimal("0.00"))
        txs.append(
            Transaction(
                chunk_id=_CHUNK_ID,
                date=date(2025, 4, i + 1),
                description=f"deposit_{i}",
                amount=amount,
                direction="credit",
                running_balance=stated_rb,
            )
        )
    # Summary uses correct sums (total=80, ending=1080) — chain breaks at
    # row 4 but per-row amounts still total correctly so C6 stays silent.
    summary = _summary(
        beginning="1000.00",
        ending="1080.00",
        deposits_total="80.00",
        deposits_count=8,
    )
    report = verify_chunk(summary, txs)

    chain_break_suspects = [s for s in report.suspects if s.code == "balance_chain_break"]
    summary_delta_suspects = [s for s in report.suspects if s.code == "summary_delta"]
    assert len(chain_break_suspects) == 1, (
        f"Expected 1 balance_chain_break, got {chain_break_suspects}"
    )
    assert chain_break_suspects[0].row_index == 4

    # C6 must stay SILENT — the per-row amounts still sum correctly to the
    # summary, only the running_balance column is shifted.  This is the entire
    # design rationale for the +$50 cascade; assert it explicitly.
    assert summary_delta_suspects == [], (
        f"Expected no summary_delta suspects, got {summary_delta_suspects}"
    )

    # Gap with missing_amount matching the introduced $50 offset.
    assert len(report.gaps) >= 1
    gap = report.gaps[0]
    assert abs(gap.missing_amount) == Decimal("50.00"), (
        f"Expected gap.missing_amount=50.00, got {gap.missing_amount}"
    )


# ---------------------------------------------------------------------------
# Test 3 — date inversion
# ---------------------------------------------------------------------------


def test_verifier_date_inversion() -> None:
    """Swapping rows 3 and 4 dates → exactly 1 date_order suspect."""
    txs = [
        _tx(i=0, amount="100.00", tx_date=date(2025, 4, 1)),
        _tx(i=1, amount="100.00", tx_date=date(2025, 4, 2)),
        _tx(i=2, amount="100.00", tx_date=date(2025, 4, 5)),  # row 2: Apr 5
        _tx(i=3, amount="100.00", tx_date=date(2025, 4, 3)),  # row 3: Apr 3 < Apr 5 → inverted
        _tx(i=4, amount="100.00", tx_date=date(2025, 4, 6)),
    ]
    summary = _summary(beginning="0.00", deposits_total="500.00", deposits_count=5)
    report = verify_chunk(summary, txs)

    date_order_suspects = [s for s in report.suspects if s.code == "date_order"]
    assert len(date_order_suspects) == 1, (
        f"Expected 1 date_order suspect, got {date_order_suspects}"
    )
    assert date_order_suspects[0].row_index == 3


# ---------------------------------------------------------------------------
# Test 4 — duplicate row
# ---------------------------------------------------------------------------


def test_verifier_duplicate_row() -> None:
    """Identical row copied → 1 duplicate_row suspect.

    Total = 100 + 100 + 250 + 100 + 100 + 250 = 900; summary is set to match
    so C6 stays silent and only C3 fires.
    """
    original = _tx(i=0, amount="250.00", description="WIRE TRANSFER", tx_date=date(2025, 4, 5))
    dupe = _tx(i=5, amount="250.00", description="WIRE TRANSFER", tx_date=date(2025, 4, 5))
    txs = [
        _tx(i=1, amount="100.00", tx_date=date(2025, 4, 1)),
        _tx(i=2, amount="100.00", tx_date=date(2025, 4, 2)),
        original,
        _tx(i=3, amount="100.00", tx_date=date(2025, 4, 6)),
        _tx(i=4, amount="100.00", tx_date=date(2025, 4, 7)),
        dupe,
    ]
    # actual sum: 100+100+250+100+100+250 = 900; set summary to match so C6 stays silent
    summary = _summary(beginning="0.00", deposits_total="900.00", deposits_count=6)
    report = verify_chunk(summary, txs)

    dup_suspects = [s for s in report.suspects if s.code == "duplicate_row"]
    assert len(dup_suspects) == 1, f"Expected 1 duplicate_row suspect, got {dup_suspects}"
    assert dup_suspects[0].row_index == 5  # the second occurrence


# ---------------------------------------------------------------------------
# Test 5 — pseudo-row description
# ---------------------------------------------------------------------------


def test_verifier_pseudo_row() -> None:
    """Injecting description='BEGINNING BALANCE' → 1 empty_description suspect."""
    txs = [
        _tx(i=0, amount="100.00", description="BEGINNING BALANCE"),
        _tx(i=1, amount="200.00", description="PAYROLL DEPOSIT"),
        _tx(i=2, amount="50.00", direction="debit", description="ELECTRIC BILL"),
    ]
    summary = _summary(
        beginning="0.00",
        deposits_total="300.00",
        deposits_count=2,
        withdrawals_total="50.00",
        withdrawals_count=1,
    )
    report = verify_chunk(summary, txs)

    empty_desc_suspects = [s for s in report.suspects if s.code == "empty_description"]
    assert len(empty_desc_suspects) == 1, (
        f"Expected 1 empty_description suspect, got {empty_desc_suspects}"
    )
    assert empty_desc_suspects[0].row_index == 0


# ---------------------------------------------------------------------------
# Test 6 — zero amount
# ---------------------------------------------------------------------------


def test_verifier_zero_amount() -> None:
    """Row with amount=0 → 1 zero_amount suspect.

    Transaction._coerce_amount raises on amount < 0 but allows amount == 0
    (validator: `if d < Decimal('0'): raise`).  Zero is therefore valid
    at the model level and we can construct directly without model_construct.
    """
    txs = [
        _tx(i=0, amount="100.00"),
        _tx(i=1, amount="0.00"),  # zero amount — header/separator row
        _tx(i=2, amount="50.00"),
    ]
    summary = _summary(beginning="0.00", deposits_total="150.00", deposits_count=3)
    report = verify_chunk(summary, txs)

    zero_suspects = [s for s in report.suspects if s.code == "zero_amount"]
    assert len(zero_suspects) == 1, f"Expected 1 zero_amount suspect, got {zero_suspects}"
    assert zero_suspects[0].row_index == 1


# ---------------------------------------------------------------------------
# Test 7 — summary delta (no running_balance)
# ---------------------------------------------------------------------------


def test_verifier_summary_delta() -> None:
    """Sum of rows ≠ summary; all running_balance=None → summary_delta at row_index=0."""
    txs = [
        _tx(i=0, amount="100.00"),
        _tx(i=1, amount="100.00"),
        _tx(i=2, amount="100.00"),
    ]
    # State: deposits_total=300, but summary claims ending=1500 (beginning=1000 + delta=200)
    summary = Summary(
        chunk_id=_CHUNK_ID,
        beginning_balance=Decimal("1000.00"),
        ending_balance=Decimal("1500.00"),  # implies 500 credits, but we only have 300
        deposits_total=Decimal("500.00"),
        deposits_count=3,
        withdrawals_total=Decimal("0.00"),
        withdrawals_count=0,
    )
    report = verify_chunk(summary, txs)

    delta_suspects = [s for s in report.suspects if s.code == "summary_delta"]
    assert len(delta_suspects) == 1, f"Expected 1 summary_delta suspect, got {delta_suspects}"
    # No running_balance on any row → breaker=None → row_index=0
    assert delta_suspects[0].row_index == 0


# ---------------------------------------------------------------------------
# Test 8 — confidence formula
# ---------------------------------------------------------------------------


def test_verifier_confidence() -> None:
    """N=2 suspects on M=10 rows → confidence == Decimal('0.80') (1 - 2/10).

    Strategy: use exactly 2 empty_description suspects on rows 2 and 7 of a
    10-row chunk whose running_balance chain is fully consistent and whose sum
    matches the summary exactly.  This guarantees C1, C3, C5, C6 are all
    silent; only C4 fires twice, giving total_suspects == 2 and an exact
    confidence of 0.80.
    """
    amount = Decimal("100.00")
    total = amount * 10  # 1000.00
    txs: list[Transaction] = []
    for i in range(10):
        # Rows 2 and 7 get the pseudo-row description that triggers C4.
        desc = "BEGINNING BALANCE" if i in (2, 7) else f"deposit_{i}"
        txs.append(
            Transaction(
                chunk_id=_CHUNK_ID,
                date=date(2025, 4, i + 1),
                description=desc,
                amount=amount,
                direction="credit",
                running_balance=None,  # omit running_balance so C1 never fires
            )
        )
    summary = _summary(
        beginning="0.00",
        ending=str(total),
        deposits_total=str(total),
        deposits_count=10,
    )
    report = verify_chunk(summary, txs)

    # Exactly 2 suspects — both from C4 (empty_description).
    assert len(report.suspects) == 2, f"Expected exactly 2 suspects, got {report.suspects}"
    assert all(s.code == "empty_description" for s in report.suspects)

    # confidence = 1 - 2/10 = 0.80
    assert report.confidence == Decimal("0.80"), (
        f"Expected confidence=0.80, got {report.confidence}"
    )


# ---------------------------------------------------------------------------
# Test 9 — verifier(state) graph-node wrapper
# ---------------------------------------------------------------------------


def test_verifier_node_wrapper_groups_by_chunk_id() -> None:
    """``verifier(state)`` reads summaries+transactions from state and emits
    one VerifierReport per chunk_id.
    """
    from src.nodes.verifier import verifier

    summary_a = Summary(
        chunk_id="period_01",
        beginning_balance=Decimal("100.00"),
        ending_balance=Decimal("110.00"),
        deposits_total=Decimal("10.00"),
        deposits_count=1,
        withdrawals_total=Decimal("0.00"),
        withdrawals_count=0,
    )
    summary_b = Summary(
        chunk_id="period_02",
        beginning_balance=Decimal("200.00"),
        ending_balance=Decimal("190.00"),
        deposits_total=Decimal("0.00"),
        deposits_count=0,
        withdrawals_total=Decimal("10.00"),
        withdrawals_count=1,
    )
    tx_a = Transaction(
        chunk_id="period_01",
        date=date(2025, 4, 1),
        description="deposit",
        amount=Decimal("10.00"),
        direction="credit",
        running_balance=Decimal("110.00"),
    )
    tx_b = Transaction(
        chunk_id="period_02",
        date=date(2025, 5, 1),
        description="withdrawal",
        amount=Decimal("10.00"),
        direction="debit",
        running_balance=Decimal("190.00"),
    )

    state: dict[str, object] = {
        "summaries": [summary_a, summary_b],
        "transactions": [tx_a, tx_b],
    }
    delta = verifier(state)  # type: ignore[arg-type]

    assert "verifier_reports" in delta
    reports = delta["verifier_reports"]
    assert isinstance(reports, list)
    assert len(reports) == 2

    by_id = {r.chunk_id: r for r in reports}
    assert set(by_id) == {"period_01", "period_02"}
    # Both periods are clean → confidence==1.00 and no suspects.
    for r in reports:
        assert isinstance(r, VerifierReport)
        assert r.confidence == Decimal("1.00")
        assert r.suspects == []
        assert r.gaps == []

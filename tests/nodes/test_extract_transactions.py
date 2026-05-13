"""Tests for src/nodes/extract_transactions.py — business-intent assertions (rule 9).

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from src.models import PeriodChunk

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "period_01",
    pdf_text: str = "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28 598,877.98",
    ocr_slice: str | None = None,
) -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 5),
        pdf_text=pdf_text,
        ocr_slice=ocr_slice,
    )


class _FakeRow:
    """Minimal _TransactionRow-like object for tests — no chunk_id."""

    def __init__(
        self,
        tx_date: date,
        description: str,
        amount: Decimal,
        direction: str,
        running_balance: Decimal | None = None,
    ) -> None:
        self.date = tx_date
        self.description = description
        self.amount = amount
        self.direction = direction
        self.running_balance = running_balance

    def model_dump(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "description": self.description,
            "amount": self.amount,
            "direction": self.direction,
            "running_balance": self.running_balance,
        }


def _make_transaction_list_result(rows: list[_FakeRow]) -> Any:
    """Return a mock _TransactionList-like object with a .transactions attribute."""
    result = MagicMock()
    result.transactions = rows
    return result


def _mock_llm_returning(rows: list[_FakeRow]) -> MagicMock:
    """Mock that behaves like ChatAnthropic(...).with_structured_output(_TransactionList)."""
    structured = MagicMock()
    structured.invoke.return_value = _make_transaction_list_result(rows)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# Test 1 — happy path: 3-row list returned, all chunk_ids overwritten
# ---------------------------------------------------------------------------


def test_extract_transactions_happy_path() -> None:
    """Mock LLM returns 3 transactions; all must have chunk_id overwritten from input."""
    from src.nodes.extract_transactions import extract_transactions

    llm_txs = [
        _FakeRow(
            date(2025, 4, 1), "VENDOR PMT", Decimal("1809.28"), "credit", Decimal("598877.98")
        ),
        _FakeRow(
            date(2025, 4, 2), "ACH PAYMENT", Decimal("5000.00"), "debit", Decimal("593877.98")
        ),
        _FakeRow(date(2025, 4, 3), "CHECK 40861", Decimal("617.16"), "debit", Decimal("593260.82")),
    ]
    mock_llm = _mock_llm_returning(llm_txs)
    chunk = _make_chunk(chunk_id="period_01")

    with patch("src.nodes.extract_transactions._get_llm", return_value=mock_llm):
        result = extract_transactions(chunk)

    assert "transactions" in result
    txs = result["transactions"]
    assert len(txs) == 3
    for tx in txs:
        assert tx.chunk_id == "period_01", (
            f"chunk_id must be overwritten from input chunk, got {tx.chunk_id!r}"
        )
    assert "errors" not in result


# ---------------------------------------------------------------------------
# Test 2 — error path: ValidationError → empty list + error entry
# ---------------------------------------------------------------------------


def test_extract_transactions_error_path_returns_empty() -> None:
    """ValidationError from LLM causes fallback to empty list with error entry."""
    from src.nodes.extract_transactions import extract_transactions

    structured = MagicMock()
    # Raise ValidationError by constructing one from pydantic
    structured.invoke.side_effect = ValueError("synthetic failure")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_04")

    with patch("src.nodes.extract_transactions._get_llm", return_value=llm):
        result = extract_transactions(chunk)

    assert result["transactions"] == []
    assert "errors" in result
    assert any("period_04" in e and "ValueError" in e for e in result["errors"]), (
        f"Expected error mentioning chunk_id and exception class, got {result['errors']}"
    )


# ---------------------------------------------------------------------------
# Test 3 — cache discipline: stable prefix has ephemeral, dynamic block does not
# ---------------------------------------------------------------------------


def test_extract_transactions_cache_discipline() -> None:
    """Stable prefix block carries cache_control ephemeral; dynamic block does not."""
    from src.nodes.extract_transactions import extract_transactions

    captured_messages: list[Any] = []

    def _capture_invoke(messages: list[Any]) -> Any:
        captured_messages.extend(messages)
        return _make_transaction_list_result([])

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="DYNAMIC_TX_CHUNK_TEXT")

    with patch("src.nodes.extract_transactions._get_llm", return_value=llm):
        extract_transactions(chunk)

    # Two messages: SystemMessage (cached prefix) + HumanMessage (dynamic).
    assert len(captured_messages) == 2, (
        f"expected 2 messages (system + human), got {len(captured_messages)}"
    )
    system_msg, user_msg = captured_messages
    assert isinstance(system_msg.content, list)
    assert len(system_msg.content) == 1
    stable = system_msg.content[0]
    assert stable.get("cache_control") == {"type": "ephemeral"}
    assert "DYNAMIC_TX_CHUNK_TEXT" not in stable["text"], (
        "stable prefix must NOT contain the dynamic chunk text"
    )
    assert "DYNAMIC_TX_CHUNK_TEXT" in user_msg.content, (
        f"HumanMessage must carry the chunk text verbatim, got {user_msg.content!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — dynamic block contains chunk_id, beginning_balance, and chunk text
# ---------------------------------------------------------------------------


def test_extract_transactions_dynamic_block_contains_metadata() -> None:
    """Dynamic block must contain chunk_id=, beginning_balance=, and the chunk text."""
    from src.nodes.extract_transactions import extract_transactions

    dynamic_texts: list[str] = []

    def _capture_invoke(messages: list[Any]) -> Any:
        # Dynamic block (chunk_id + beginning_balance + chunk text) is on
        # the HumanMessage now; SystemMessage carries only the cached prefix.
        for msg in messages:
            if isinstance(msg.content, str):
                dynamic_texts.append(msg.content)
        return _make_transaction_list_result([])

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="2025-04-01:1664", pdf_text="THE_ACTUAL_CHUNK_BODY")

    with patch("src.nodes.extract_transactions._get_llm", return_value=llm):
        extract_transactions(chunk)

    assert dynamic_texts, "dynamic block text was not captured"
    dynamic = dynamic_texts[0]
    assert "chunk_id=2025-04-01:1664" in dynamic, (
        f"dynamic block must contain chunk_id=, got: {dynamic[:200]!r}"
    )
    assert "beginning_balance=unknown" in dynamic, (
        f"dynamic block must contain beginning_balance=unknown sentinel, got: {dynamic[:200]!r}"
    )
    assert "THE_ACTUAL_CHUNK_BODY" in dynamic, (
        f"dynamic block must contain the chunk text, got: {dynamic[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — running_balance Decimal precision preserved through LLM output
# ---------------------------------------------------------------------------


def test_extract_transactions_running_balance_decimal_preserved() -> None:
    """running_balance=Decimal('598877.98') must survive the LLM output path without
    float-representation drift (CLAUDE.md: Decimal, not float).
    """
    from src.nodes.extract_transactions import extract_transactions

    precise_balance = Decimal("598877.98")
    llm_row = _FakeRow(
        tx_date=date(2025, 4, 1),
        description="AIRLINEHYD 2759/VENDOR PMT",
        amount=Decimal("1809.28"),
        direction="credit",
        running_balance=precise_balance,
    )
    mock_llm = _mock_llm_returning([llm_row])
    chunk = _make_chunk(chunk_id="period_01")

    with patch("src.nodes.extract_transactions._get_llm", return_value=mock_llm):
        result = extract_transactions(chunk)

    tx = result["transactions"][0]
    assert tx.running_balance == precise_balance, (
        f"running_balance precision lost: expected {precise_balance}, got {tx.running_balance}"
    )
    assert isinstance(tx.running_balance, Decimal), (
        f"running_balance must be Decimal, got {type(tx.running_balance)}"
    )

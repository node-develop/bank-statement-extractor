"""Tests for src/nodes/extract_summary.py — business-intent assertions.

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from src.models import PeriodChunk, Summary

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "period_01",
    pdf_text: str = "Beginning Balance as of 04/01/2025   $597,068.70",
    ocr_slice: str | None = None,
) -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 2),
        pdf_text=pdf_text,
        ocr_slice=ocr_slice,
    )


def _make_summary(chunk_id: str = "ignored") -> Summary:
    return Summary(
        chunk_id=chunk_id,
        beginning_balance=Decimal("597068.70"),
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )


def _mock_llm_returning(summary: Summary) -> MagicMock:
    """Return a mock that behaves like ChatAnthropic(...).with_structured_output(Summary)."""
    structured = MagicMock()
    structured.invoke.return_value = summary
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# Test 1 — happy path: chunk_id is overwritten from the input chunk
# ---------------------------------------------------------------------------


def test_extract_summary_happy_path() -> None:
    """LLM returns a Summary; chunk_id must be overwritten from the input chunk."""
    from src.nodes.extract_summary import extract_summary

    llm_summary = _make_summary(chunk_id="ignored")
    mock_llm = _mock_llm_returning(llm_summary)
    chunk = _make_chunk(chunk_id="period_01")

    with patch("src.nodes.extract_summary._get_llm", return_value=mock_llm):
        result = extract_summary(chunk)

    assert "summaries" in result
    assert len(result["summaries"]) == 1
    summary = result["summaries"][0]
    assert summary.chunk_id == "period_01", (
        f"chunk_id must be overwritten from input chunk, got {summary.chunk_id!r}"
    )
    assert summary.deposits_count == 81
    assert summary.withdrawals_count == 111
    assert "errors" not in result


# ---------------------------------------------------------------------------
# Test 2 — error path: LLM raises → placeholder all-zero Summary + error
# ---------------------------------------------------------------------------


def test_extract_summary_error_path_returns_placeholder() -> None:
    """ValueError from LLM causes fallback to all-zero Summary with error entry."""
    from src.nodes.extract_summary import extract_summary

    structured = MagicMock()
    structured.invoke.side_effect = ValueError("synthetic failure")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_03")

    with patch("src.nodes.extract_summary._get_llm", return_value=llm):
        result = extract_summary(chunk)

    assert "summaries" in result
    summary = result["summaries"][0]
    assert summary.chunk_id == "period_03"
    assert summary.beginning_balance == Decimal("0.00")
    assert summary.ending_balance == Decimal("0.00")
    assert summary.deposits_total == Decimal("0.00")
    assert summary.deposits_count == 0
    assert summary.withdrawals_total == Decimal("0.00")
    assert summary.withdrawals_count == 0

    assert "errors" in result
    assert any("period_03" in e and "ValueError" in e for e in result["errors"]), (
        f"Expected error mentioning chunk_id and exception class, got {result['errors']}"
    )


# ---------------------------------------------------------------------------
# Test 3 — cache discipline: stable prefix has ephemeral, dynamic block does not
# ---------------------------------------------------------------------------


def test_extract_summary_cache_discipline() -> None:
    """Stable prefix block carries cache_control ephemeral; dynamic block does not.
    Dynamic block contains chunk text verbatim; stable block does not.
    """
    from src.nodes.extract_summary import extract_summary

    captured_messages: list[Any] = []

    def _capture_invoke(messages: list[Any]) -> Summary:
        captured_messages.extend(messages)
        return _make_summary(chunk_id="period_01")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="DYNAMIC_CHUNK_TEXT_SUMMARY")

    with patch("src.nodes.extract_summary._get_llm", return_value=llm):
        extract_summary(chunk)

    # Two messages: SystemMessage (cached prefix) + HumanMessage (dynamic).
    assert len(captured_messages) == 2, (
        f"expected 2 messages (system + human), got {len(captured_messages)}"
    )
    system_msg, user_msg = captured_messages
    assert isinstance(system_msg.content, list)
    assert len(system_msg.content) == 1
    stable = system_msg.content[0]
    assert stable.get("cache_control") == {"type": "ephemeral"}
    assert "DYNAMIC_CHUNK_TEXT_SUMMARY" not in stable["text"], (
        "stable prefix must NOT contain the dynamic chunk text"
    )
    assert "DYNAMIC_CHUNK_TEXT_SUMMARY" in user_msg.content, (
        f"HumanMessage must carry the chunk text verbatim, got {user_msg.content!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — truncation: 10 000-char pdf_text is clipped to 6 000 chars
# ---------------------------------------------------------------------------


def test_extract_summary_truncates_large_text() -> None:
    """pdf_text longer than 6 000 chars must be truncated before sending to the LLM."""
    from src.nodes.extract_summary import _MAX_INPUT_CHARS, extract_summary

    long_text = "B" * 10_000
    received_texts: list[str] = []

    def _capture_invoke(messages: list[Any]) -> Summary:
        # Dynamic chunk text now lives on the HumanMessage; SystemMessage
        # carries only the cached stable prefix.
        for msg in messages:
            if isinstance(msg.content, str):
                received_texts.append(msg.content)
        return _make_summary(chunk_id="period_01")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text=long_text)

    with patch("src.nodes.extract_summary._get_llm", return_value=llm):
        extract_summary(chunk)

    assert received_texts, "dynamic block text was not captured"
    assert len(received_texts[0]) <= _MAX_INPUT_CHARS, (
        f"Expected text <= {_MAX_INPUT_CHARS} chars, got {len(received_texts[0])}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Decimal precision: Apr-2025 etalon round-trips through JSON
# ---------------------------------------------------------------------------


def test_extract_summary_decimal_precision_round_trip() -> None:
    """Decimal values from the Apr-2025 etalon must survive a JSON round-trip
    without precision loss (Decimal, not float).
    """
    from src.nodes.extract_summary import extract_summary

    etalon_summary = _make_summary(chunk_id="ignored")
    mock_llm = _mock_llm_returning(etalon_summary)
    chunk = _make_chunk(chunk_id="2025-04-01:1664")

    with patch("src.nodes.extract_summary._get_llm", return_value=mock_llm):
        result = extract_summary(chunk)

    summary = result["summaries"][0]
    # Serialize to JSON (model_dump_json uses quoted-string Decimal serializer)
    json_str = summary.model_dump_json()
    data = json.loads(json_str)

    assert Decimal(data["beginning_balance"]) == Decimal("597068.70")
    assert Decimal(data["ending_balance"]) == Decimal("509121.59")
    assert Decimal(data["deposits_total"]) == Decimal("1214254.05")
    assert Decimal(data["withdrawals_total"]) == Decimal("1302201.16")

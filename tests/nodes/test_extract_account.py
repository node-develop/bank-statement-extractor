"""Tests for src/nodes/extract_account.py — business-intent assertions.

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from src.models import Account, Period, PeriodChunk

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "period_01",
    pdf_text: str = "Ixonia Bank\nAccount Number: 1664\nBeginning Balance as of 04/01/2025",
    ocr_slice: str | None = None,
    account_hint_last4: str | None = "1664",
) -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 2),
        pdf_text=pdf_text,
        ocr_slice=ocr_slice,
        account_hint_last4=account_hint_last4,
    )


def _make_account(chunk_id: str = "ignored", account_last4: str = "1664") -> Account:
    return Account(
        chunk_id=chunk_id,
        bank="Ixonia Bank",
        account_last4=account_last4,
        period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
    )


def _mock_llm_returning(account: Account) -> MagicMock:
    """Return a mock that behaves like ChatAnthropic(...).with_structured_output(Account)."""
    structured = MagicMock()
    structured.invoke.return_value = account
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# Test 1 — happy path: chunk_id is overwritten from the input chunk
# ---------------------------------------------------------------------------


def test_extract_account_happy_path() -> None:
    """LLM returns an Account; chunk_id must be overwritten from the input chunk."""
    from src.nodes.extract_account import extract_account

    llm_account = _make_account(chunk_id="ignored", account_last4="1664")
    mock_llm = _mock_llm_returning(llm_account)
    chunk = _make_chunk(chunk_id="period_01")

    with patch("src.nodes.extract_account._get_llm", return_value=mock_llm):
        result = extract_account(chunk)

    assert "accounts" in result
    assert len(result["accounts"]) == 1
    account = result["accounts"][0]
    assert account.chunk_id == "period_01", (
        f"chunk_id must be overwritten from input chunk, got {account.chunk_id!r}"
    )
    assert account.bank == "Ixonia Bank"
    assert account.account_last4 == "1664"
    assert "errors" not in result


# ---------------------------------------------------------------------------
# Test 2 — error path: LLM raises → placeholder Account + error entry
# ---------------------------------------------------------------------------


def test_extract_account_error_path_returns_placeholder() -> None:
    """ValueError from LLM causes fallback to placeholder Account with error entry."""
    from src.nodes.extract_account import extract_account

    structured = MagicMock()
    structured.invoke.side_effect = ValueError("synthetic failure")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_03", account_hint_last4="1664")

    with patch("src.nodes.extract_account._get_llm", return_value=llm):
        result = extract_account(chunk)

    assert "accounts" in result
    account = result["accounts"][0]
    # Placeholder uses the chunk's account_hint_last4
    assert account.account_last4 == "1664"
    assert "errors" in result
    assert any("period_03" in e and "ValueError" in e for e in result["errors"]), (
        f"Expected error mentioning chunk_id and exception class, got {result['errors']}"
    )


def test_extract_account_error_path_no_hint_uses_0000() -> None:
    """When account_hint_last4 is None, placeholder falls back to '0000'."""
    from src.nodes.extract_account import extract_account

    structured = MagicMock()
    structured.invoke.side_effect = ValueError("no hint")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_05", account_hint_last4=None)

    with patch("src.nodes.extract_account._get_llm", return_value=llm):
        result = extract_account(chunk)

    assert result["accounts"][0].account_last4 == "0000"


# ---------------------------------------------------------------------------
# Test 3 — cache discipline: stable prefix has ephemeral, dynamic block does not
# ---------------------------------------------------------------------------


def test_extract_account_cache_discipline() -> None:
    """Stable prefix block carries cache_control ephemeral; dynamic block does not.
    Dynamic block contains chunk text verbatim; stable block does not.
    """
    from src.nodes.extract_account import extract_account

    captured_messages: list[Any] = []

    def _capture_invoke(messages: list[Any]) -> Account:
        captured_messages.extend(messages)
        return _make_account(chunk_id="period_01")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="DYNAMIC_CHUNK_TEXT_ACCOUNT")

    with patch("src.nodes.extract_account._get_llm", return_value=llm):
        extract_account(chunk)

    # Two messages: SystemMessage (cached stable prefix) + HumanMessage (dynamic).
    # Anthropic requires ≥1 user message in messages[]; sending only a
    # SystemMessage returns 400 "messages: at least one message is required".
    assert len(captured_messages) == 2, (
        f"expected 2 messages (system + human), got {len(captured_messages)}"
    )
    system_msg, user_msg = captured_messages
    assert isinstance(system_msg.content, list), (
        "system message must use the multi-block content form for cache_control"
    )
    assert len(system_msg.content) == 1, (
        f"stable prefix must be a single block, got {len(system_msg.content)}"
    )
    stable = system_msg.content[0]
    assert stable.get("cache_control") == {"type": "ephemeral"}, (
        "stable prefix must have cache_control ephemeral"
    )
    assert "DYNAMIC_CHUNK_TEXT_ACCOUNT" not in stable["text"], (
        "stable prefix must NOT contain the dynamic chunk text"
    )
    assert "DYNAMIC_CHUNK_TEXT_ACCOUNT" in user_msg.content, (
        f"HumanMessage must carry the chunk text verbatim, got {user_msg.content!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — truncation: 10 000-char pdf_text is clipped to 6 000 chars
# ---------------------------------------------------------------------------


def test_extract_account_truncates_large_text() -> None:
    """pdf_text longer than 6 000 chars must be truncated before sending to the LLM."""
    from src.nodes.extract_account import _MAX_INPUT_CHARS, extract_account

    long_text = "A" * 10_000
    received_texts: list[str] = []

    def _capture_invoke(messages: list[Any]) -> Account:
        # Dynamic chunk text now lives on the HumanMessage (messages[1]).content;
        # SystemMessage holds only the stable cached prefix.
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                received_texts.append(content)
        return _make_account(chunk_id="period_01")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text=long_text)

    with patch("src.nodes.extract_account._get_llm", return_value=llm):
        extract_account(chunk)

    assert received_texts, "dynamic block text was not captured"
    assert len(received_texts[0]) <= _MAX_INPUT_CHARS, (
        f"Expected text <= {_MAX_INPUT_CHARS} chars, got {len(received_texts[0])}"
    )

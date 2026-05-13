"""Tests for src/nodes/classify_layout.py — business-intent assertions.

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.
"""

from __future__ import annotations

from typing import Any, Literal
from unittest.mock import MagicMock, patch

from src.models import LayoutLabel, PeriodChunk

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "period_01",
    pdf_text: str = "",
    ocr_slice: str | None = None,
) -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 1),
        pdf_text=pdf_text,
        ocr_slice=ocr_slice,
    )


def _mock_llm_returning(
    label: Literal["ixonia_business_basic", "generic_us_bank", "unknown"],
    chunk_id: str = "ignored",
) -> MagicMock:
    """Return a mock that behaves like ChatAnthropic(...).with_structured_output(LayoutLabel)."""
    structured = MagicMock()
    structured.invoke.return_value = LayoutLabel(chunk_id=chunk_id, label=label)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# Test 1 — happy path: chunk_id is overwritten from the input chunk
# ---------------------------------------------------------------------------


def test_classify_layout_happy_path() -> None:
    """LLM returns a label; the node must overwrite chunk_id from the input chunk."""
    from src.nodes.classify_layout import classify_layout

    mock_llm = _mock_llm_returning("ixonia_business_basic", chunk_id="ignored")
    chunk = _make_chunk(
        chunk_id="period_01",
        pdf_text=(
            "BUSINESS BASIC PLUS CHK\n"
            "Account Number: 1664\n"
            "Beginning Balance as of 04/01/2025\n"
            "$597,068.70\n"
        ),
    )

    with patch("src.nodes.classify_layout._get_llm", return_value=mock_llm):
        result = classify_layout(chunk)

    assert "layouts" in result
    assert len(result["layouts"]) == 1
    layout = result["layouts"][0]
    assert layout.label == "ixonia_business_basic"
    # chunk_id must come from the *input* chunk, not the LLM mock's "ignored"
    assert layout.chunk_id == "period_01", (
        f"chunk_id must be overwritten from input chunk, got {layout.chunk_id!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — error path: LLM raises ValueError → return "unknown" + error entry
# ---------------------------------------------------------------------------


def test_classify_layout_error_path_returns_unknown() -> None:
    """Any of the allowed exceptions causes fallback to 'unknown' with an error entry."""
    from src.nodes.classify_layout import classify_layout

    # Make the LLM raise when invoked
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("synthetic")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_03", pdf_text="some text")

    with patch("src.nodes.classify_layout._get_llm", return_value=llm):
        result = classify_layout(chunk)

    assert result["layouts"][0].label == "unknown"
    assert "errors" in result
    assert any("period_03" in e and "ValueError" in e for e in result["errors"]), (
        f"Expected error mentioning chunk_id and exception class, got {result['errors']}"
    )


# ---------------------------------------------------------------------------
# Test 3 — prefers pdf_text when both pdf_text and ocr_slice are present
# ---------------------------------------------------------------------------


def test_classify_layout_prefers_pdf_text() -> None:
    """When pdf_text is non-empty, it is passed to the LLM, not ocr_slice."""
    from src.nodes.classify_layout import classify_layout

    received_prompts: list[str] = []

    def _capture_invoke(messages: list[Any]) -> LayoutLabel:
        # Capture the text content of the first (system) message
        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        received_prompts.append(block["text"])
            elif isinstance(content, str):
                received_prompts.append(content)
        return LayoutLabel(chunk_id="period_01", label="ixonia_business_basic")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="PDFLINE", ocr_slice="OCRLINE")

    with patch("src.nodes.classify_layout._get_llm", return_value=llm):
        classify_layout(chunk)

    combined = " ".join(received_prompts)
    assert "PDFLINE" in combined, "Expected PDFLINE (from pdf_text) in the prompt"
    assert "OCRLINE" not in combined, "OCRLINE (from ocr_slice) must NOT appear in the prompt"


# ---------------------------------------------------------------------------
# Test 4 — falls back to ocr_slice when pdf_text is empty
# ---------------------------------------------------------------------------


def test_classify_layout_falls_back_to_ocr_when_pdf_empty() -> None:
    """When pdf_text is '', ocr_slice is sent to the LLM."""
    from src.nodes.classify_layout import classify_layout

    received_prompts: list[str] = []

    def _capture_invoke(messages: list[Any]) -> LayoutLabel:
        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        received_prompts.append(block["text"])
            elif isinstance(content, str):
                received_prompts.append(content)
        return LayoutLabel(chunk_id="period_01", label="generic_us_bank")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="", ocr_slice="OCRLINE")

    with patch("src.nodes.classify_layout._get_llm", return_value=llm):
        classify_layout(chunk)

    combined = " ".join(received_prompts)
    assert "OCRLINE" in combined, (
        "Expected OCRLINE (from ocr_slice) in the prompt when pdf_text is empty"
    )


# ---------------------------------------------------------------------------
# Test 5 — prompt caching: stable prefix is cached, dynamic chunk text is not
# ---------------------------------------------------------------------------


def test_classify_layout_caches_stable_prefix_separately() -> None:
    """Architecture.md prompt-cache discipline: the stable prefix MUST be its
    own content block with ``cache_control: ephemeral`` so the 10-period
    fan-out reuses the cached prefix; the dynamic chunk text MUST be a
    second block WITHOUT cache_control so it doesn't poison the cache key.
    """
    from src.nodes.classify_layout import classify_layout

    captured_messages: list[Any] = []

    def _capture_invoke(messages: list[Any]) -> LayoutLabel:
        captured_messages.extend(messages)
        return LayoutLabel(chunk_id="period_01", label="ixonia_business_basic")

    structured = MagicMock()
    structured.invoke.side_effect = _capture_invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    chunk = _make_chunk(chunk_id="period_01", pdf_text="DYNAMIC_CHUNK_TEXT")

    with patch("src.nodes.classify_layout._get_llm", return_value=llm):
        classify_layout(chunk)

    # Two messages: SystemMessage (cached prefix) + HumanMessage (dynamic).
    # Anthropic requires ≥1 user message in messages[] — sending only the
    # SystemMessage returns 400 "messages: at least one message is required".
    assert len(captured_messages) == 2, (
        f"expected 2 messages (system + human), got {len(captured_messages)}"
    )
    system_msg, user_msg = captured_messages
    assert isinstance(system_msg.content, list)
    assert len(system_msg.content) == 1
    stable = system_msg.content[0]
    assert stable.get("cache_control") == {"type": "ephemeral"}
    assert "DYNAMIC_CHUNK_TEXT" not in stable["text"], (
        "stable prefix must NOT contain the dynamic chunk text"
    )
    assert user_msg.content == "DYNAMIC_CHUNK_TEXT", (
        f"HumanMessage must carry the chunk text verbatim, got {user_msg.content!r}"
    )

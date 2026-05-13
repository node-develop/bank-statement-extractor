"""Tests for src/nodes/split_periods.py — business-intent assertions (rule 9).

The Ixonia regression fixture tests run against Task/ixonia_binder2_ocr.txt
(read-only).  They are skipped when the fixture is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from src.graph.state import GraphState

_IXONIA_OCR = Path("Task/ixonia_binder2_ocr.txt")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    ocr_text: str | None,
    pages: list[str] | None = None,
) -> GraphState:
    """Build a minimal GraphState-shaped dict for split_periods."""
    from src.models import RawStatement

    if pages is None:
        pages = []
    # page_count must equal len(pages) per RawStatement validator;
    # if pages is empty we cannot build a valid RawStatement (page_count > 0).
    # Use a sentinel page list of length 1 when we only care about ocr_text.
    _pages = pages if pages else [""]
    raw = RawStatement(
        pages=_pages,
        ocr_text=ocr_text,
        sha256="a" * 64,
        page_count=len(_pages),
    )
    return cast(
        "GraphState",
        {
            "pdf_path": "dummy.pdf",
            "txt_path": None,
            "raw": raw,
            "period_chunks": [],
            "layouts": [],
            "accounts": [],
            "summaries": [],
            "transactions": [],
            "reconciliations": [],
            "retry_count": 0,
            "errors": [],
        },
    )


# ---------------------------------------------------------------------------
# Ixonia regression fixture tests (require Task/ixonia_binder2_ocr.txt)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ixonia_result() -> dict[str, Any]:
    """Run split_periods once on the Ixonia OCR fixture; cache the result."""
    if not _IXONIA_OCR.exists():
        pytest.skip("Task/ixonia_binder2_ocr.txt not present in this environment")
    from src.nodes.split_periods import split_periods

    ocr_text = _IXONIA_OCR.read_text(encoding="utf-8")
    state = _make_state(ocr_text)
    return split_periods(state)


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_chunk_count(ixonia_result: dict[str, Any]) -> None:
    """Assert exactly 10 period chunks are produced from the Ixonia OCR."""
    chunks = ixonia_result["period_chunks"]
    assert len(chunks) == 10, f"Expected 10 chunks, got {len(chunks)}"


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_chunk_ids(ixonia_result: dict[str, Any]) -> None:
    """Assert chunk_ids are period_01 through period_10 in order."""
    chunks = ixonia_result["period_chunks"]
    expected = [f"period_{i:02d}" for i in range(1, 11)]
    assert [c.chunk_id for c in chunks] == expected


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_apr_2025_account(ixonia_result: dict[str, Any]) -> None:
    """period_01 (Apr 2025): two-line form, account_hint_last4 == '1664'."""
    chunk = ixonia_result["period_chunks"][0]
    assert chunk.account_hint_last4 == "1664", (
        f"Apr 2025 account hint: expected '1664', got {chunk.account_hint_last4!r}"
    )


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_may_2025_account(ixonia_result: dict[str, Any]) -> None:
    """period_02 (May 2025): single-line masked 'XXXXXX4664', account_hint_last4 == '4664'."""
    chunk = ixonia_result["period_chunks"][1]
    assert chunk.account_hint_last4 == "4664", (
        f"May 2025 account hint: expected '4664', got {chunk.account_hint_last4!r}"
    )


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_sep_2024_4623_account(ixonia_result: dict[str, Any]) -> None:
    """period_07 (Sep 2024, second account 4623): account_hint_last4 == '4623'."""
    chunk = ixonia_result["period_chunks"][6]
    assert chunk.account_hint_last4 == "4623", (
        f"Sep 2024 4623 account hint: expected '4623', got {chunk.account_hint_last4!r}"
    )


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_nov_2024_account_missing(ixonia_result: dict[str, Any]) -> None:
    """period_09 (Nov 2024): account number not in OCR → account_hint_last4 is None."""
    chunk = ixonia_result["period_chunks"][8]
    assert chunk.account_hint_last4 is None, (
        f"Nov 2024 account hint: expected None (OCR omission), got {chunk.account_hint_last4!r}"
    )


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_nov_2024_error_surfaced(ixonia_result: dict[str, Any]) -> None:
    """An error referencing the Nov 2024 lookback miss must be in errors[]."""
    errors = ixonia_result["errors"]
    assert any("7591" in e or "11/2024" in e for e in errors), (
        f"Expected error mentioning '7591' or '11/2024', got errors={errors}"
    )


@pytest.mark.skipif(
    not _IXONIA_OCR.exists(),
    reason="Task/ixonia_binder2_ocr.txt not present in this environment",
)
def test_ixonia_apr_2025_ocr_slice_starts_with_beg(ixonia_result: dict[str, Any]) -> None:
    """period_01 ocr_slice must start with the Beginning Balance line."""
    chunk = ixonia_result["period_chunks"][0]
    assert chunk.ocr_slice is not None
    assert chunk.ocr_slice.startswith("Beginning Balance as of 04/01/2025"), (
        f"ocr_slice must start with the Beginning Balance line, got: {chunk.ocr_slice[:60]!r}"
    )


# ---------------------------------------------------------------------------
# Unit tests — synthetic OCR snippets, no fixture dependency
# ---------------------------------------------------------------------------


def test_split_periods_single_line_account() -> None:
    """Single-line 'Account Number: XXXXXX4664' is found via the lookback."""
    from src.nodes.split_periods import split_periods

    ocr = (
        "BUSINESS BASIC PLUS CHK\n"
        "Account Number: XXXXXX4664\n"
        "Balance Summary\n"
        "Beginning Balance as of 05/01/2025\n"
        "$100.00\n"
        "Ending Balance as of 05/31/2025\n"
        "$90.00\n"
    )
    result = split_periods(_make_state(ocr))
    chunks = result["period_chunks"]
    assert len(chunks) == 1
    assert chunks[0].account_hint_last4 == "4664"


def test_split_periods_two_line_account() -> None:
    """Two-line 'Account Number:\\n1664' form is found via the lookback."""
    from src.nodes.split_periods import split_periods

    ocr = (
        "BUSINESS BASIC PLUS CHK\n"
        "Account Number:\n"
        "1664\n"
        "Balance Summary\n"
        "Beginning Balance as of 04/01/2025\n"
        "$597,068.70\n"
        "Ending Balance as of 04/30/2025\n"
        "$509,121.59\n"
    )
    result = split_periods(_make_state(ocr))
    chunks = result["period_chunks"]
    assert len(chunks) == 1
    assert chunks[0].account_hint_last4 == "1664"


def test_split_periods_image_based_pdf_emits_actionable_error() -> None:
    """Image-based PDF (pdfplumber returns 0 chars) gets a user-facing error."""
    from src.nodes.split_periods import split_periods

    # _make_state default `pages=[""]` simulates pdfplumber returning nothing.
    result = split_periods(_make_state(None))
    assert result["period_chunks"] == []
    assert any("image-based" in e for e in result["errors"]), (
        f"Expected 'image-based' error, got {result['errors']}"
    )


def test_split_periods_empty_ocr_text_and_no_pages_returns_empty() -> None:
    """Empty-string OCR with empty pages → still 0 chunks."""
    from src.nodes.split_periods import split_periods

    result = split_periods(_make_state("   \n  "))
    assert result["period_chunks"] == []
    assert any("image-based" in e for e in result["errors"])


def test_split_periods_falls_back_to_pdfplumber_pages_when_no_ocr() -> None:
    """No OCR but pdfplumber pages have real text → 1 whole-doc chunk, no error noise."""
    from src.nodes.split_periods import split_periods

    pages = [
        "Bank of Example — Statement\nAccount Number: 1234\n",
        "01/02/2025  Deposit  $100.00  $1,100.00\n",
    ]
    result = split_periods(_make_state(None, pages=pages))
    chunks = result["period_chunks"]
    assert len(chunks) == 1, f"Expected 1 fallback chunk, got {len(chunks)}: {chunks}"
    assert chunks[0].chunk_id == "period_01"
    assert chunks[0].account_hint_last4 == "1234"
    assert "Bank of Example" in (chunks[0].ocr_slice or "")
    # Fallback success is informational only — must NOT emit a user-facing error.
    assert result["errors"] == [], (
        f"Successful fallback should produce no errors, got {result['errors']}"
    )


def test_split_periods_ocr_slice_spans_beg_to_end() -> None:
    """The ocr_slice of a chunk must span from the BEG anchor to the END anchor."""
    from src.nodes.split_periods import split_periods

    ocr = (
        "Account Number: 9999\n"
        "Beginning Balance as of 01/01/2025\n"
        "$500.00\n"
        "mid-period transaction line\n"
        "Ending Balance as of 01/31/2025\n"
        "$450.00\n"
    )
    result = split_periods(_make_state(ocr))
    chunks = result["period_chunks"]
    assert len(chunks) == 1
    assert chunks[0].ocr_slice is not None
    # Slice spans from this period's Beginning anchor to the NEXT period's
    # Beginning anchor (or end-of-file for the last/only period).  Transaction
    # rows in real bank layouts appear AFTER the "Ending Balance" line, so the
    # slice MUST include everything up to the file end here.
    assert chunks[0].ocr_slice.startswith("Beginning Balance as of 01/01/2025")
    assert "mid-period transaction line" in chunks[0].ocr_slice
    assert "Ending Balance as of 01/31/2025" in chunks[0].ocr_slice
    assert chunks[0].ocr_slice.rstrip().endswith("$450.00")

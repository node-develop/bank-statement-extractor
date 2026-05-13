"""Tests for src/nodes/ingest.py — business-intent assertions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from src.graph.state import GraphState

_IXONIA_PDF = Path("Task/Binder2_Redacted.pdf")
_IXONIA_OCR = Path("Task/ixonia_binder2_ocr.txt")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(pdf_path: str, txt_path: str | None = None) -> GraphState:
    return cast(
        "GraphState",
        {
            "pdf_path": pdf_path,
            "txt_path": txt_path,
            "raw": None,
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


def _minimal_pdf_bytes() -> bytes:
    """Return a minimal valid PDF byte string using pypdf's writer."""
    from io import BytesIO

    import pypdf

    buf = BytesIO()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Test 1 — smoke test on real Ixonia fixture
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _IXONIA_PDF.exists(),
    reason="Task/Binder2_Redacted.pdf not present in this environment",
)
def test_ingest_smoke_on_ixonia() -> None:
    from src.nodes.ingest import ingest

    result = ingest(_make_state(str(_IXONIA_PDF), str(_IXONIA_OCR)))

    raw = result["raw"]
    assert raw.page_count > 90, f"Expected >90 pages, got {raw.page_count}"
    assert len(raw.sha256) == 64, "sha256 must be 64 hex characters"
    assert all(c in "0123456789abcdef" for c in raw.sha256), "sha256 must be lowercase hex"
    assert raw.ocr_text is not None, "OCR text must be loaded when txt_path is given"
    assert len(raw.ocr_text) > 100_000, f"OCR text expected >100k chars, got {len(raw.ocr_text)}"


# ---------------------------------------------------------------------------
# Test 2 — sha256 is deterministic for identical bytes
# ---------------------------------------------------------------------------


def test_ingest_sha256_deterministic(tmp_path: Path) -> None:
    from src.nodes.ingest import ingest

    pdf_bytes = _minimal_pdf_bytes()
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    pdf_a.write_bytes(pdf_bytes)
    pdf_b.write_bytes(pdf_bytes)

    result_a = ingest(_make_state(str(pdf_a)))
    result_b = ingest(_make_state(str(pdf_b)))

    assert result_a["raw"].sha256 == result_b["raw"].sha256, (
        "sha256 must be identical for identical file bytes"
    )


# ---------------------------------------------------------------------------
# Test 3 — pypdf fallback when pdfplumber raises OSError
# ---------------------------------------------------------------------------


def test_ingest_pypdf_fallback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    with (
        patch("src.nodes.ingest._extract_with_pdfplumber", return_value=[]),
        caplog.at_level(logging.WARNING, logger="src.nodes.ingest"),
    ):
        result = ingest(_make_state(str(pdf_path)))

    assert result["raw"].page_count >= 1, "pypdf fallback must return at least one page"
    # Warning is emitted by the caller when pdfplumber returns empty
    assert "fallback" in caplog.text.lower(), (
        "Expected a WARNING mentioning 'fallback' when pdfplumber returns no pages"
    )


# ---------------------------------------------------------------------------
# Test 4 — unreadable file raises RuntimeError
# ---------------------------------------------------------------------------


def test_ingest_unreadable_raises(tmp_path: Path) -> None:
    from src.nodes.ingest import ingest

    bad_file = tmp_path / "garbage.pdf"
    bad_file.write_bytes(b"\x00\x01\x02\x03NOTAPDF" * 100)

    with pytest.raises(RuntimeError, match="PDF unreadable"):
        ingest(_make_state(str(bad_file)))


# ---------------------------------------------------------------------------
# Test 5 — OCR text is loaded from txt_path
# ---------------------------------------------------------------------------


def test_ingest_ocr_text_loaded(tmp_path: Path) -> None:
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())
    ocr_path = tmp_path / "ocr.txt"
    ocr_content = "This is the OCR text for the statement.\nLine two.\n"
    ocr_path.write_text(ocr_content, encoding="utf-8")

    result = ingest(_make_state(str(pdf_path), str(ocr_path)))

    assert result["raw"].ocr_text == ocr_content, (
        "ocr_text must equal the content of the txt file verbatim"
    )


# ---------------------------------------------------------------------------
# Test 6 — empty pdfplumber page surfaces error in errors[]
# ---------------------------------------------------------------------------


def test_ingest_empty_page_surfaces_error(tmp_path: Path) -> None:
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    ocr_text = "Some OCR content that is non-empty"

    # Patch _extract_with_pdfplumber to return one empty page + one dense page.
    # Page 2 is intentionally long so the per-page average is above the OCR
    # threshold (50 chars) — we want to exercise the empty-page flag, NOT the
    # OCR fallback. Without this, ingest would invoke ocrmypdf on the blank PDF.
    mock_pages = ["", "some content on page 2 " * 20]

    with patch("src.nodes.ingest._extract_with_pdfplumber", return_value=mock_pages):
        result = ingest(_make_state(str(pdf_path), None))
        # No ocr_text yet — no errors should be appended for empty pages without OCR
        assert result["errors"] == [], "No errors expected when ocr_text is None"

    # Now with ocr_text provided — expect the error to be surfaced
    ocr_path = tmp_path / "ocr.txt"
    ocr_path.write_text(ocr_text, encoding="utf-8")

    with patch("src.nodes.ingest._extract_with_pdfplumber", return_value=mock_pages):
        result2 = ingest(_make_state(str(pdf_path), str(ocr_path)))

    assert any("page 1" in e or "empty" in e.lower() for e in result2["errors"]), (
        f"Expected an error mentioning 'page 1' or 'empty', got errors={result2['errors']}"
    )


# ---------------------------------------------------------------------------
# Test 7 — OCR fallback engages on image-based PDF when no .txt supplied
# ---------------------------------------------------------------------------


def test_ingest_ocr_fallback_engages(tmp_path: Path) -> None:
    """Image-based PDF without .txt companion → ocrmypdf runs server-side.

    Asserts the business intent: txt_path is optional, and the service must
    handle scanned bank statements end-to-end.
    """
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    fake_pages = ["page one OCR text", "page two OCR text"]
    fake_full = "page one OCR text\fpage two OCR text"

    with (
        patch("src.nodes.ingest._extract_with_pdfplumber", return_value=["", ""]),
        patch(
            "src.nodes.ingest._run_tesseract_ocr",
            return_value=(fake_pages, fake_full),
        ),
    ):
        result = ingest(_make_state(str(pdf_path), None))

    assert result["raw"].ocr_text == fake_full, "OCR sidecar text must reach raw.ocr_text"
    assert result["raw"].pages == fake_pages, "OCR pages must replace empty pdfplumber pages"
    # OCR engagement is informational — goes to notes[], not errors[].
    assert result["errors"] == [], f"OCR success must not write to errors[]; got {result['errors']}"
    assert any("OCR fallback engaged" in n for n in result["notes"]), (
        f"Expected notes[] to record OCR ran; got {result['notes']}"
    )


# ---------------------------------------------------------------------------
# Test 8 — OCR fallback skipped when extracted text is dense
# ---------------------------------------------------------------------------


def test_ingest_ocr_fallback_skipped_on_dense_text(tmp_path: Path) -> None:
    """A PDF with a real text layer should NOT invoke ocrmypdf."""
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "dense.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    dense_pages = ["a" * 500, "b" * 500]  # avg = 500 chars/page, well above 50

    with (
        patch("src.nodes.ingest._extract_with_pdfplumber", return_value=dense_pages),
        patch("src.nodes.ingest._run_tesseract_ocr") as ocr_mock,
    ):
        result = ingest(_make_state(str(pdf_path), None))

    ocr_mock.assert_not_called()
    assert result["raw"].ocr_text is None, "ocr_text should remain None on dense text"
    assert result["raw"].pages == dense_pages, "dense pages must pass through unchanged"


# ---------------------------------------------------------------------------
# Test 9 — Caller-supplied .txt overrides server-side OCR
# ---------------------------------------------------------------------------


def test_ingest_ocr_fallback_skipped_with_companion_txt(tmp_path: Path) -> None:
    """If the user attaches their own OCR text, do NOT run Tesseract.

    Honors the "Advanced: attach .txt" override on the frontend — when present,
    the caller knows better.
    """
    from src.nodes.ingest import ingest

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())
    ocr_path = tmp_path / "manual.txt"
    ocr_path.write_text("manually attached OCR text", encoding="utf-8")

    with (
        patch("src.nodes.ingest._extract_with_pdfplumber", return_value=["", ""]),
        patch("src.nodes.ingest._run_tesseract_ocr") as ocr_mock,
    ):
        result = ingest(_make_state(str(pdf_path), str(ocr_path)))

    ocr_mock.assert_not_called()
    assert result["raw"].ocr_text == "manually attached OCR text"


# ---------------------------------------------------------------------------
# Test 10 — OCR fallback failure is reported via errors[], no crash
# ---------------------------------------------------------------------------


def test_ingest_ocr_fallback_failure_reported(tmp_path: Path) -> None:
    """When ocrmypdf fails (missing binary, corrupt PDF, etc.), ingest must NOT
    crash — the failure is surfaced via errors[] so the user sees what happened."""
    from src.nodes.ingest import OcrFallbackError, ingest

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    with (
        patch("src.nodes.ingest._extract_with_pdfplumber", return_value=["", ""]),
        patch(
            "src.nodes.ingest._run_tesseract_ocr",
            side_effect=OcrFallbackError("simulated tesseract binary missing"),
        ),
    ):
        result = ingest(_make_state(str(pdf_path), None))

    assert result["raw"].ocr_text is None, "ocr_text remains None when OCR fails"
    assert any("OCR fallback failed" in e for e in result["errors"]), (
        f"Expected errors[] to flag OCR failure; got {result['errors']}"
    )

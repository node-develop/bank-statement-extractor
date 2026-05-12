"""``ingest`` graph node — load a PDF and optional OCR text into ``GraphState``.

Source-selection policy (architecture.md "ingest" node):

- pdfplumber is the primary PDF text extractor.
- On pdfplumber failure, fall back to pypdf.
- If both fail or produce zero pages, raise ``RuntimeError``.
- pdfplumber output is primary for ``raw.pages``.
- Pages where pdfplumber returns empty text are flagged in ``errors[]``
  when ``ocr_text`` is available; page-aligned OCR substitution is deferred
  to a later milestone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import RawStatement

logger = get_logger(__name__)


def ingest(state: GraphState) -> dict[str, Any]:
    """Load a PDF + optional OCR text; return a partial state delta.

    Parameters
    ----------
    state:
        Must supply ``pdf_path`` (str) and ``txt_path`` (str | None).

    Returns
    -------
    dict
        Keys ``"raw"`` (``RawStatement``) and ``"errors"`` (``list[str]``).

    Raises
    ------
    RuntimeError
        When both pdfplumber and pypdf fail to produce any pages from the
        given file.  Maps to HTTP 422 in the API layer.
    """
    pdf_path: str = state["pdf_path"]
    txt_path: str | None = state["txt_path"]
    errors: list[str] = []

    pdf_bytes = Path(pdf_path).read_bytes()
    sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
    logger.info("ingest: starting sha256=%.12s... path=%s", sha256_hex, pdf_path)

    pages = _extract_with_pdfplumber(pdf_path, sha256_hex)

    if not pages:
        logger.warning(
            "ingest: pdfplumber produced 0 pages; falling back to pypdf path=%s", pdf_path
        )
        pages = _extract_with_pypdf(pdf_path)

    if not pages:
        raise RuntimeError(
            f"ingest: PDF unreadable — both pdfplumber and pypdf returned no pages: {pdf_path}"
        )

    ocr_text: str | None = None
    if txt_path is not None:
        ocr_text = Path(txt_path).read_text(encoding="utf-8")

    # Source-selection policy: flag pages where pdfplumber returned empty text
    # when OCR text is available (rule 7 — surface, don't average).
    if ocr_text:
        for i, page_text in enumerate(pages):
            if not page_text.strip():
                errors.append(
                    f"ingest: page {i + 1} returned empty from pdfplumber; "
                    "OCR text is available at raw.ocr_text but page-aligned "
                    "slicing is not implemented in M1"
                )

    raw = RawStatement(
        pages=pages,
        ocr_text=ocr_text,
        sha256=sha256_hex,
        page_count=len(pages),
    )
    return {"raw": raw, "errors": errors}


def _extract_with_pdfplumber(pdf_path: str, sha256_hex: str) -> list[str]:
    """Attempt to extract per-page text with pdfplumber.

    Returns an empty list (not raises) on library-level parse failures so
    the caller can fall back to pypdf.
    """
    try:
        import pdfplumber
        from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException
    except ImportError:
        # pdfplumber not installed in this environment; caller falls back.
        return []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except (PdfminerException, MalformedPDFException, OSError, ValueError) as exc:
        logger.warning(
            "ingest: pdfplumber failed sha256=%.12s... error=%s; will attempt pypdf fallback",
            sha256_hex,
            exc,
        )
        return []


def _extract_with_pypdf(pdf_path: str) -> list[str]:
    """Attempt to extract per-page text with pypdf.

    Returns an empty list (not raises) so the caller can decide whether
    to raise ``RuntimeError``.
    """
    try:
        import pypdf
        from pypdf.errors import PyPdfError
    except ImportError:
        return []

    try:
        reader = pypdf.PdfReader(pdf_path)
        return [page.extract_text() or "" for page in reader.pages]
    except (PyPdfError, OSError) as exc:
        logger.warning("ingest: pypdf also failed path=%s error=%s", pdf_path, exc)
        return []

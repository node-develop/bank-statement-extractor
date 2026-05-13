"""``ingest`` graph node — load a PDF and optional OCR text into ``GraphState``.

Source-selection policy (architecture.md "ingest" node):

- pdfplumber is the primary PDF text extractor.
- On pdfplumber failure, fall back to pypdf.
- If both fail or produce zero pages, raise ``RuntimeError``.
- pdfplumber output is primary for ``raw.pages``.
- When neither pdfplumber nor pypdf yields meaningful text (image-based PDF)
  AND no ``ocr_text`` companion was supplied, fall back to server-side
  Tesseract OCR via ``ocrmypdf``. Engages only when the average extracted
  text per page is below ``_OCR_AVG_CHARS_PER_PAGE`` — a noisy scan with a
  few real characters does not trigger OCR (rule 7 — surface, don't average;
  the engine is recorded in ``errors[]`` so the user can see what happened).
- Pages where pdfplumber returns empty text are flagged in ``errors[]``
  when ``ocr_text`` is available; page-aligned OCR substitution is deferred
  to a later milestone.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import RawStatement

logger = get_logger(__name__)


# Below this average chars/page across the pdfplumber+pypdf output, treat the
# document as image-based and engage Tesseract. A real bank-statement page
# carries on the order of 1.5-3k characters; 50 is well below any signal.
_OCR_AVG_CHARS_PER_PAGE = 50


class OcrFallbackError(RuntimeError):
    """Raised when ocrmypdf is required but cannot run (missing binary, etc.)."""


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
    notes: list[str] = []

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

    # OCR fallback: when the user did NOT supply a .txt companion and the
    # extracted text density is below threshold, the PDF is image-based.
    # Engine selection: Azure Document Intelligence (preferred — matches
    # Task/ixonia_binder2_ocr.txt baseline which reconciles 100% on Ixonia)
    # when AZURE_DI_ENDPOINT + AZURE_DI_KEY env vars are set; otherwise
    # fallback to ocrmypdf/Tesseract (self-hosted, no key required).
    if ocr_text is None:
        total_chars = sum(len(p) for p in pages)
        avg_chars = total_chars / len(pages)
        if avg_chars < _OCR_AVG_CHARS_PER_PAGE:
            engine = _pick_ocr_engine()
            logger.info(
                "ingest: avg_chars_per_page=%.1f below %d; engaging %s (pages=%d, sha256=%.12s...)",
                avg_chars,
                _OCR_AVG_CHARS_PER_PAGE,
                engine,
                len(pages),
                sha256_hex,
            )
            try:
                if engine == "azure_di":
                    ocr_pages, ocr_text = _run_azure_di_ocr(pdf_path)
                else:
                    ocr_pages, ocr_text = _run_tesseract_ocr(pdf_path)
            except OcrFallbackError as exc:
                # OCR failure IS a real error — pipeline degrades to no-text.
                logger.warning("ingest: OCR fallback failed (%s): %s", engine, exc)
                errors.append(f"ingest: OCR fallback failed engine={engine} error={exc}")
            else:
                # Surface the engine choice as an informational note (rule 12
                # — surface uncertainty). NOT an error; the UI renders notes
                # in a distinct, non-alarming info block.
                notes.append(
                    f"OCR fallback engaged: {engine} ran server-side on {len(ocr_pages)} "
                    f"image-based pages, produced {len(ocr_text):,} characters of text."
                )
                # Replace pdfplumber's empty pages with OCR'd text so the
                # downstream page-range lookup in split_periods works.
                if ocr_pages:
                    pages = ocr_pages

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
    return {"raw": raw, "errors": errors, "notes": notes}


def _pick_ocr_engine() -> str:
    """Return ``"azure_di"`` if Azure DI env vars are set, else ``"tesseract"``.

    Decision is made per-call (cheap env lookup) so the container can be
    configured at runtime without a rebuild. Per task.md, txt_path is optional
    and the service must handle unseen banks — Azure DI matches the working
    baseline (Task/ixonia_binder2_ocr.txt is Azure DI output).
    """
    if os.environ.get("AZURE_DI_ENDPOINT") and os.environ.get("AZURE_DI_KEY"):
        return "azure_di"
    return "tesseract"


def _run_azure_di_ocr(pdf_path: str) -> tuple[list[str], str]:
    """Run Azure Document Intelligence prebuilt-read on the PDF.

    Uses the `prebuilt-read` model — cheapest tier, returns plain text + a
    per-page structure. We reconstruct per-page text from `page.lines` and
    join with form-feed (\\f) to mirror the shape `_run_tesseract_ocr`
    returns, so the rest of the pipeline (split_periods, page-range lookup)
    works identically regardless of engine.

    Returns
    -------
    (pages, full_text)
        ``pages`` is per-page OCR text (one entry per source page).
        ``full_text`` is the same content joined with form-feed.

    Raises
    ------
    OcrFallbackError
        On missing env vars, ImportError, or any SDK error.
    """
    endpoint = os.environ.get("AZURE_DI_ENDPOINT")
    key = os.environ.get("AZURE_DI_KEY")
    if not endpoint or not key:
        raise OcrFallbackError("Azure DI env vars missing (AZURE_DI_ENDPOINT, AZURE_DI_KEY)")

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:  # pragma: no cover — exercised only when not installed
        raise OcrFallbackError(f"azure-ai-documentintelligence not installed: {exc}") from exc

    client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    try:
        with open(pdf_path, "rb") as fh:
            # `prebuilt-layout` (not `prebuilt-read`) is what produced the
            # working Task/ixonia_binder2_ocr.txt baseline: it preserves
            # table structure, which is critical for bank-statement summaries
            # (Balance Summary / Deposits / Withdrawals appear in multi-column
            # blocks).
            # Default output format is TEXT (plain). We deliberately do NOT
            # use MARKDOWN here — markdown prefixes "Beginning Balance as
            # of..." headings with `##`, which breaks the split_periods
            # anchor regex and collapses the whole document into a single
            # chunk. Plain text preserves the line shape the regex expects.
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=fh,
            )
            result = poller.result()
    except Exception as exc:
        raise OcrFallbackError(f"Azure DI invocation failed: {exc}") from exc

    # result.content is the FULL document text (markdown). For the per-page
    # split, slice using page.spans (offset+length into result.content).
    full_text: str = result.content or ""
    pages: list[str] = []
    for page in result.pages or []:
        page_parts: list[str] = []
        for sp in page.spans or []:
            start = int(sp.offset)
            end = start + int(sp.length)
            page_parts.append(full_text[start:end])
        pages.append("".join(page_parts))

    # Edge case: no per-page spans (rare; older API versions) — return a
    # single-page slice so downstream nodes see at least one page entry.
    if not pages:
        pages = [full_text]

    return pages, full_text


def _run_tesseract_ocr(pdf_path: str) -> tuple[list[str], str]:
    """Run ocrmypdf on an image-based PDF and return its extracted text.

    Uses ocrmypdf's sidecar mode: the OCR text is written to a separate
    plain-text file (one form-feed ``\\f`` per page), and the output PDF is
    discarded — we only care about the text. ``force_ocr=True`` because the
    caller already determined that no native text layer is present.

    Returns
    -------
    (pages, full_text)
        ``pages`` is the per-page OCR text (form-feed split, trailing empty
        element trimmed). ``full_text`` is the raw sidecar content (form-feed
        separated) suitable for ``RawStatement.ocr_text``.

    Raises
    ------
    OcrFallbackError
        On ImportError (ocrmypdf not installed) or any ocrmypdf error.
    """
    try:
        import ocrmypdf
    except ImportError as exc:  # pragma: no cover — exercised only when not installed
        raise OcrFallbackError(f"ocrmypdf not installed: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="bsa-ocr-") as td:
        sidecar = Path(td) / "sidecar.txt"
        try:
            # output_file="-" + output_type="none" tells ocrmypdf 17.x to skip
            # writing a PDF entirely; we only want the sidecar text. Without
            # the `-`, OcrOptions validation rejects the call.
            #
            # Tesseract tuning experiment (2026-05-13): oversample=400,
            # tesseract_pagesegmode=6, tesseract_oem=1, disable dawgs,
            # deskew/clean. Empirical result on Task/Binder2_Redacted.pdf:
            # 3x slower (6m18 vs 2m13), 2 periods lost (8 vs 10), account
            # digits still mis-recognised. Digit confusion is font-level —
            # not fixable by Tesseract config. Default settings restored.
            # See docs/architecture.md for the Azure DI escalation path.
            ocrmypdf.ocr(
                input_file_or_options=pdf_path,
                output_file="-",
                sidecar=str(sidecar),
                force_ocr=True,
                language=["eng"],
                progress_bar=False,
                output_type="none",
            )
        except Exception as exc:
            raise OcrFallbackError(f"ocrmypdf invocation failed: {exc}") from exc

        if not sidecar.exists():
            raise OcrFallbackError(f"ocrmypdf produced no sidecar at {sidecar}")

        full_text = sidecar.read_text(encoding="utf-8")
        # Form-feed splits pages; a trailing empty element is common.
        parts = full_text.split("\f")
        if parts and parts[-1] == "":
            parts.pop()
        return parts, full_text


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

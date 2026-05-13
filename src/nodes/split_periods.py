"""``split_periods`` graph node — deterministic OCR-text period splitter.

Pure Python, no LLM (CLAUDE.md rule 5).  Splits the full OCR text into one
``PeriodChunk`` per statement period using regex anchors and a line-scan.

Ixonia regression fixture (architecture.md):
  10 chunks expected, Beginning Balance anchors at OCR lines (1-based):
  38, 1133, 2379, 3399, 4410, 5297, 6280, 6620, 7591, 8632.
"""

from __future__ import annotations

import re
from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import PeriodChunk

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Compiled regexes (module-level, compile once)
# ---------------------------------------------------------------------------

# Primary period anchors.
# OCR engines disagree on column layout. Three real-world shapes seen so far:
#   (a) Azure DI stream  — "...as of 04/01/2025"            (year is line-end)
#   (b) Tesseract stream — "...as of 04/01/2025 $597,068.70" (amount appended)
#   (c) Azure DI table   — "...as of 05/01/2025 | $509, 121.59"  (pipe-delimited)
# We want to match (a) and (b) once per period, but NOT (c) — it's the same
# period repeated in a structured-table recap section, and counting it
# produces duplicate chunks. The negative lookahead `(?!\s*\|)` excludes (c).
# \s+ between tokens absorbs Tesseract's stray double-spaces; \d{1,2} allows
# OCR-dropped leading zeros; IGNORECASE handles "BEGINNING BALANCE".
_BEG = re.compile(
    r"^Beginning\s+Balance\s+as\s+of\s+(\d{1,2})/(\d{1,2})/(\d{4})\b(?!\s*\|)",
    re.IGNORECASE,
)
_END = re.compile(
    r"^Ending\s+Balance\s+as\s+of\s+(\d{1,2})/(\d{1,2})/(\d{4})\b(?!\s*\|)",
    re.IGNORECASE,
)

# Account-number patterns
# Single-line form: "Account Number: XXXXXX4664" or "Account Number: 4664"
_ACCT_SINGLE = re.compile(r"^Account Number:\s*(?:XXXXXX)?(\d{4})\s*$")
# Two-line form — first line is exactly "Account Number:" (stripped),
# subsequent line is digits (with optional XXXXXX prefix)
_ACCT_LABEL = re.compile(r"^Account Number:\s*$")
_ACCT_DIGITS = re.compile(r"^(?:XXXXXX)?(\d{4})\s*$")

# Generic mid-line form for non-Ixonia layouts (Chase/BofA/Wells Fargo/PNC):
#   "HOUSTON TX 77032-1184 Account Number: ****8421"
#   "Account Number: xxxx-1234"
# Anywhere in the line, with any masking prefix before the final 4 digits.
_ACCT_ANYWHERE = re.compile(r"Account\s*(?:Number|Num|#)\s*[:\.]?\s*[\*xX\-\s]*(\d{4})\b")

_LOOKBACK = 20  # max lines before Beginning anchor to scan for account number


def split_periods(state: GraphState) -> dict[str, Any]:
    """Split ``raw.ocr_text`` into one ``PeriodChunk`` per detected period.

    Returns a partial state delta with keys ``"period_chunks"``, ``"errors"``
    (real failures), and ``"notes"`` (informational — e.g. the cheap regex
    couldn't infer account_last4, but ``extract_account`` will still try via
    LLM). Never calls an LLM — on regex miss the function logs a specific
    note and returns whatever complete chunks it could build.
    """
    raw = state["raw"]
    ocr_text: str | None = raw.ocr_text
    errors: list[str] = []
    notes: list[str] = []

    # OCR is optional. When the caller did not supply a .txt companion (or
    # supplied an empty one), fall back to the pdfplumber-extracted per-page
    # text joined into a single string. Regex anchors may not match the
    # pdfplumber output (different whitespace + line breaks than Azure OCR),
    # but the whole-doc fallback below (n_chunks == 0) still emits one
    # chunk covering the entire document. The extractor prompts handle the
    # rest via few-shot exemplars.
    if ocr_text is None or not ocr_text.strip():
        joined_pages = "\n".join(raw.pages) if raw.pages else ""
        if joined_pages.strip():
            logger.info(
                "split_periods: raw.ocr_text empty; falling back to "
                "%d pdfplumber pages joined as text",
                len(raw.pages),
            )
            # Informational only — do NOT pollute the user-facing errors[]
            # channel when the fallback completes successfully.
            ocr_text = joined_pages
        else:
            # The ingest node already attempted Tesseract OCR before we got
            # here (see src/nodes/ingest.py:_run_tesseract_ocr). If we still
            # have no text, OCR genuinely produced nothing — either the PDF
            # is blank, severely corrupted, or Tesseract failed to install.
            # Report the catastrophe; do NOT instruct the user to "attach"
            # anything (the API contract is one file = the PDF).
            logger.warning(
                "split_periods: no text available after pdfplumber, pypdf, and OCR fallback "
                "(see errors[] for engine details)"
            )
            return {
                "period_chunks": [],
                "errors": [
                    "split_periods: no text extracted from this PDF — "
                    "pdfplumber, pypdf, and the OCR fallback all produced empty output. "
                    "The document may be blank, password-protected, or corrupted."
                ],
            }

    lines = ocr_text.splitlines()

    # ------------------------------------------------------------------
    # Scan once for all Beginning and Ending anchors
    # ------------------------------------------------------------------
    beg_matches: list[tuple[int, re.Match[str]]] = []
    end_matches: list[tuple[int, re.Match[str]]] = []

    for idx, line in enumerate(lines):
        m = _BEG.match(line)
        if m:
            beg_matches.append((idx, m))
            continue
        m = _END.match(line)
        if m:
            end_matches.append((idx, m))

    if len(beg_matches) != len(end_matches):
        n_beg, n_end = len(beg_matches), len(end_matches)
        # Informational — we still build min(n_beg, n_end) chunks, so this is
        # a partial-success notice, not a hard error.
        notes.append(
            f"split_periods: found {n_beg} Beginning anchors but "
            f"{n_end} Ending anchors; building {min(n_beg, n_end)} chunks"
        )

    n_chunks = min(len(beg_matches), len(end_matches))

    # ------------------------------------------------------------------
    # Fallback for non-Ixonia layouts (Chase / BofA / Wells / PNC / etc.):
    # when no "Beginning Balance as of MM/DD/YYYY" anchor matches, emit a
    # SINGLE chunk covering the whole document.  The extractor prompts
    # already handle multi-bank summaries via few-shot exemplars; their
    # only requirement is that they receive the period text.
    # ------------------------------------------------------------------
    if n_chunks == 0:
        logger.info("split_periods: no Ixonia anchors found; emitting 1 whole-doc chunk")
        whole_doc_hint = _find_account_anywhere(lines)
        pdf_text_all = "\n".join(raw.pages) if raw.pages else ""
        first_page, last_page = (1, max(len(raw.pages), 1))
        chunks: list[PeriodChunk] = [
            PeriodChunk(
                chunk_id="period_01",
                page_range=(first_page, last_page),
                pdf_text=pdf_text_all,
                ocr_slice=ocr_text,
                account_hint_last4=whole_doc_hint,
            )
        ]
        return {"period_chunks": chunks, "errors": errors, "notes": notes}

    chunks = []

    for k in range(n_chunks):
        beg_idx, beg_m = beg_matches[k]
        _end_idx, end_m = end_matches[k]  # end_idx no longer used for slicing

        mm_beg, dd_beg, yyyy_beg = beg_m.group(1), beg_m.group(2), beg_m.group(3)
        mm_end, dd_end, yyyy_end = end_m.group(1), end_m.group(2), end_m.group(3)

        chunk_id = f"period_{k + 1:02d}"

        # Slice from this period's Beginning anchor up to (but not including)
        # the NEXT period's Beginning anchor — NOT just up to the Ending
        # Balance line. In Ixonia, "Ending Balance as of …" appears in the
        # summary block ABOVE the transaction list; if we cut at end_idx we
        # capture only ~6 lines of header and miss every transaction row.
        # Last chunk extends to the end of the file.
        if k + 1 < n_chunks:
            slice_end = beg_matches[k + 1][0]  # next period's Beginning line
        else:
            slice_end = len(lines)
        ocr_slice = "\n".join(lines[beg_idx:slice_end])

        # ------------------------------------------------------------------
        # Account-number lookback. Misses go into notes[], not errors[], because
        # the LLM-based extract_account node will still try independently — the
        # regex hint is informational, not a contract.
        # ------------------------------------------------------------------
        account_hint_last4 = _find_account_hint(lines, beg_idx, mm_beg, yyyy_beg, notes)

        # ------------------------------------------------------------------
        # Page-range alignment (best-effort, raw.pages may be empty)
        # ------------------------------------------------------------------
        beg_anchor = f"Beginning Balance as of {mm_beg}/{dd_beg}/{yyyy_beg}"
        end_anchor = f"Ending Balance as of {mm_end}/{dd_end}/{yyyy_end}"
        first_page, last_page = _find_page_range(raw.pages, beg_anchor, end_anchor)
        if raw.pages:
            pdf_text = "\n".join(raw.pages[first_page - 1 : last_page])
        else:
            pdf_text = ""

        chunks.append(
            PeriodChunk(
                chunk_id=chunk_id,
                page_range=(first_page, last_page),
                pdf_text=pdf_text,
                ocr_slice=ocr_slice,
                account_hint_last4=account_hint_last4,
            )
        )

    logger.info("split_periods: built %d chunks from %d lines", len(chunks), len(lines))
    return {"period_chunks": chunks, "errors": errors, "notes": notes}


def _find_account_hint(
    lines: list[str],
    beg_idx: int,
    mm: str,
    yyyy: str,
    notes: list[str],
) -> str | None:
    """Look back up to ``_LOOKBACK`` lines before *beg_idx* for an account number.

    Two patterns are tried in order:
    1. Single-line: ``Account Number: [XXXXXX]<4 digits>``
    2. Two-line: a line that is exactly ``Account Number:`` followed by a line
       containing ``[XXXXXX]<4 digits>`` within the next 3 lines.

    Returns the 4-digit string on match, ``None`` on miss.  Appends an
    informational note to *notes* on miss — the LLM-based ``extract_account``
    node still tries independently, so a regex miss is NOT a real error.
    """
    start = max(0, beg_idx - _LOOKBACK)
    window = lines[start:beg_idx]

    # Pass 1 — single-line form
    for line in reversed(window):
        m = _ACCT_SINGLE.match(line)
        if m:
            return m.group(1)

    # Pass 2 — two-line form: find "Account Number:" label then scan forward
    for i, line in enumerate(window):
        if _ACCT_LABEL.match(line):
            # Scan the next up to 3 lines for the digit line
            for j in range(i + 1, min(i + 4, len(window))):
                m = _ACCT_DIGITS.match(window[j])
                if m:
                    return m.group(1)

    # Neither pattern matched — informational, the LLM extractor will retry.
    notes.append(
        f"split_periods: account hint not found by regex within {_LOOKBACK} lines "
        f"before line {beg_idx + 1} (period {mm}/{yyyy}); extract_account LLM will try."
    )
    return None


def _find_account_anywhere(lines: list[str]) -> str | None:
    """Scan the whole document for ``Account Number: ****1234``-style hints.

    Used by the fallback whole-doc chunk path.  Returns the FIRST 4-digit
    match — non-Ixonia statements typically only carry one account.
    """
    for line in lines:
        m = _ACCT_ANYWHERE.search(line)
        if m:
            return m.group(1)
    return None


def _find_page_range(pages: list[str], beg_anchor: str, end_anchor: str) -> tuple[int, int]:
    """Return the 1-indexed (first_page, last_page) range containing the period.

    Scans *pages* for the first page whose text contains *beg_anchor* and the
    last page whose text contains *end_anchor*.  Falls back to ``(1, 1)`` when
    *pages* is empty or no page contains the anchor.
    """
    if not pages:
        return (1, 1)

    first_page: int | None = None
    last_page: int | None = None

    for i, page_text in enumerate(pages):
        if first_page is None and beg_anchor in page_text:
            first_page = i + 1
        if end_anchor in page_text:
            last_page = i + 1

    if first_page is None:
        first_page = 1
    if last_page is None:
        last_page = first_page

    return (first_page, last_page)

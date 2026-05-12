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

# Primary period anchors
_BEG = re.compile(r"^Beginning Balance as of (\d{2})/(\d{2})/(\d{4})\s*$")
_END = re.compile(r"^Ending Balance as of (\d{2})/(\d{2})/(\d{4})\s*$")

# Account-number patterns
# Single-line form: "Account Number: XXXXXX4664" or "Account Number: 4664"
_ACCT_SINGLE = re.compile(r"^Account Number:\s*(?:XXXXXX)?(\d{4})\s*$")
# Two-line form — first line is exactly "Account Number:" (stripped),
# subsequent line is digits (with optional XXXXXX prefix)
_ACCT_LABEL = re.compile(r"^Account Number:\s*$")
_ACCT_DIGITS = re.compile(r"^(?:XXXXXX)?(\d{4})\s*$")

_LOOKBACK = 20  # max lines before Beginning anchor to scan for account number


def split_periods(state: GraphState) -> dict[str, Any]:
    """Split ``raw.ocr_text`` into one ``PeriodChunk`` per detected period.

    Returns a partial state delta with keys ``"period_chunks"`` and
    ``"errors"``.  Never calls an LLM — on regex miss the function logs a
    specific error and returns whatever complete chunks it could build.
    """
    raw = state["raw"]
    ocr_text: str | None = raw.ocr_text

    if ocr_text is None or not ocr_text.strip():
        logger.warning("split_periods: raw.ocr_text is empty; returning no chunks")
        return {
            "period_chunks": [],
            "errors": ["split_periods: raw.ocr_text is empty"],
        }

    lines = ocr_text.splitlines()
    errors: list[str] = []

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
        errors.append(
            f"split_periods: found {n_beg} Beginning anchors but "
            f"{n_end} Ending anchors; building {min(n_beg, n_end)} chunks"
        )

    n_chunks = min(len(beg_matches), len(end_matches))
    chunks: list[PeriodChunk] = []

    for k in range(n_chunks):
        beg_idx, beg_m = beg_matches[k]
        end_idx, end_m = end_matches[k]

        mm_beg, dd_beg, yyyy_beg = beg_m.group(1), beg_m.group(2), beg_m.group(3)
        mm_end, dd_end, yyyy_end = end_m.group(1), end_m.group(2), end_m.group(3)

        chunk_id = f"period_{k + 1:02d}"
        ocr_slice = "\n".join(lines[beg_idx : end_idx + 1])

        # ------------------------------------------------------------------
        # Account-number lookback
        # ------------------------------------------------------------------
        account_hint_last4 = _find_account_hint(lines, beg_idx, mm_beg, yyyy_beg, errors)

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
    return {"period_chunks": chunks, "errors": errors}


def _find_account_hint(
    lines: list[str],
    beg_idx: int,
    mm: str,
    yyyy: str,
    errors: list[str],
) -> str | None:
    """Look back up to ``_LOOKBACK`` lines before *beg_idx* for an account number.

    Two patterns are tried in order:
    1. Single-line: ``Account Number: [XXXXXX]<4 digits>``
    2. Two-line: a line that is exactly ``Account Number:`` followed by a line
       containing ``[XXXXXX]<4 digits>`` within the next 3 lines.

    Returns the 4-digit string on match, ``None`` on miss.  Appends a
    diagnostic to *errors* on miss.
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

    # Neither pattern matched
    errors.append(
        f"split_periods: account_last4 not found within {_LOOKBACK} lines "
        f"before line {beg_idx + 1} (period {mm}/{yyyy})"
    )
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

"""``extract_summary`` graph node — extracts period monetary Summary per chunk.

Invoked once per ``PeriodChunk`` via LangGraph ``Send`` fan-out (wired in
``src/graph/builder.py``).  Uses Haiku 4.5 with Anthropic prompt caching on
the stable prompt prefix.

Never raises — on any recoverable error the node returns an all-zero Summary
and appends a diagnostic to ``errors[]``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import anthropic
from pydantic import ValidationError

from src.api.logging import get_logger
from src.api.pricing import call_cost
from src.models import PeriodChunk, Summary
from src.prompts import load_prompt

_RECOVERABLE_ERRORS = (
    anthropic.APIError,
    ValidationError,
    KeyError,
    TypeError,
    ValueError,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton LLM — instantiated on first call so imports stay cheap and
# tests can monkeypatch ``_get_llm`` before the first invocation.
# ---------------------------------------------------------------------------
_LLM_INSTANCE: Any = None

# Balance summary block lives in the header; 6 000 chars covers it comfortably.
_MAX_INPUT_CHARS = 6_000
# Smart-slice: instead of naively taking the first N chars (which can mix
# in the previous period's table recap on dense chunks where Azure DI lays
# tables out densely), anchor on the "Beginning Balance" line of THIS chunk
# and take up to _SMART_SLICE_LINES lines around it. Falls back to naive
# truncation when no anchor is found.
_SMART_SLICE_LINES = 120
_SMART_SLICE_PRE = 5  # also include a few lines BEFORE the anchor (header)


def _get_llm() -> Any:
    """Return (or create) the module-level ChatAnthropic singleton."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        from langchain_anthropic import ChatAnthropic

        _LLM_INSTANCE = ChatAnthropic(  # type: ignore[call-arg]
            model="claude-haiku-4-5",
            max_tokens=1024,
            temperature=0,
            timeout=60,
        )
    return _LLM_INSTANCE


def extract_summary(chunk: PeriodChunk) -> dict[str, Any]:
    """Extract the period monetary summary from *chunk* and return a state delta.

    Parameters
    ----------
    chunk:
        A single ``PeriodChunk`` dispatched via LangGraph ``Send``.

    Returns
    -------
    dict
        Always contains ``"summaries": [Summary]``.  Contains ``"errors"``
        only when falling back to an all-zero placeholder.
    """
    # Prefer pdf_text; fall back to ocr_slice when pdf_text is empty.
    raw_text: str = chunk.pdf_text if chunk.pdf_text else (chunk.ocr_slice or "")
    text = _smart_slice_around_summary(raw_text)
    if len(raw_text) > _MAX_INPUT_CHARS:
        logger.warning(
            "extract_summary: chunk %s text is %d chars, smart-sliced to %d",
            chunk.chunk_id,
            len(raw_text),
            len(text),
        )

    try:
        return _invoke_llm(chunk, text)
    except _RECOVERABLE_ERRORS as exc:
        zero = Decimal("0.00")
        placeholder = Summary(
            chunk_id=chunk.chunk_id,
            beginning_balance=zero,
            ending_balance=zero,
            deposits_total=zero,
            deposits_count=0,
            withdrawals_total=zero,
            withdrawals_count=0,
        )
        error_msg = (
            f"extract_summary: {chunk.chunk_id} fell back to placeholder: "
            f"{exc.__class__.__name__}: {exc}"
        )
        logger.warning(error_msg)
        return {"summaries": [placeholder], "errors": [error_msg]}


def _smart_slice_around_summary(raw_text: str) -> str:
    """Slice the chunk text around the period's Beginning Balance anchor.

    Why this beats naive ``raw_text[:N]``: on dense Azure DI layouts where
    the previous period's table recap sometimes appears at the head of the
    next chunk's slice, a head-cut grabs the WRONG period's data. The
    Balance Summary block lives within a handful of lines of the anchor —
    anchoring the slice on "Beginning Balance" guarantees we hand the LLM
    THIS period's numbers, not the previous one's.

    Falls back to ``raw_text[:_MAX_INPUT_CHARS]`` when no anchor is found.
    """
    if len(raw_text) <= _MAX_INPUT_CHARS:
        return raw_text

    lines = raw_text.split("\n")
    anchor_idx: int | None = None
    for i, line in enumerate(lines):
        # Cheap substring check — full regex is in split_periods; here we
        # just need to locate the line.
        if "Beginning Balance" in line:
            anchor_idx = i
            break

    if anchor_idx is None:
        return raw_text[:_MAX_INPUT_CHARS]

    start = max(0, anchor_idx - _SMART_SLICE_PRE)
    end = min(len(lines), anchor_idx + _SMART_SLICE_LINES)
    sliced = "\n".join(lines[start:end])
    # Still respect the hard cap (very wide lines could overflow).
    return sliced[:_MAX_INPUT_CHARS]


def _invoke_llm(chunk: PeriodChunk, text: str) -> dict[str, Any]:
    """Call the LLM with prompt caching and return the state delta.

    The stable prompt prefix (everything before ``{chunk_text}``) is sent as a
    separate content block with ``cache_control: ephemeral`` so that the prefix
    is cached and reused across the 10-period fan-out.  The dynamic chunk text
    goes in a second content block WITHOUT cache_control.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_body = load_prompt("extract_summary", version=1)
    stable_prefix, sep, _ = prompt_body.partition("{chunk_text}")
    if not sep:
        # Prompt file is malformed: missing placeholder. Use whole body as prefix.
        stable_prefix = prompt_body

    # Stable prefix → SystemMessage (cached). Dynamic chunk → HumanMessage
    # (Anthropic requires ≥1 user message in messages[]).
    system = SystemMessage(
        content=[
            {
                "type": "text",
                "text": stable_prefix,
                "cache_control": {"type": "ephemeral"},
            },
        ]
    )
    user = HumanMessage(content=text)

    # include_raw=True → {"raw": AIMessage, "parsed": Summary, "parsing_error": None}
    # so we can read usage_metadata for cost tracking (PRD §8.2).
    # Defensive: if the LLM (or a test mock) returns the parsed model directly
    # instead of the include_raw dict, fall back gracefully — usage_metadata
    # won't be available and cost will be 0 for that call.
    llm_with_output = _get_llm().with_structured_output(Summary, include_raw=True)
    invoke_result: Any = llm_with_output.invoke([system, user])
    if isinstance(invoke_result, dict):
        raw_msg = invoke_result.get("raw")
        raw_result: Summary | None = invoke_result.get("parsed")
        parsing_error = invoke_result.get("parsing_error")
        if raw_result is None:
            # The LLM produced output that failed Pydantic validation.
            # Surface as a ValueError so the extract_summary outer try/except
            # falls back to a placeholder + errors[] entry (rule 12).
            raise ValueError(
                f"extract_summary: structured-output parsed=None (parsing_error={parsing_error!r})"
            )
    else:
        raw_msg = None
        raw_result = invoke_result

    # Cost tracking — read usage_metadata from the AIMessage.
    usage_md = getattr(raw_msg, "usage_metadata", None) or {}
    this_call_cost = call_cost(_get_llm().model, usage_md if isinstance(usage_md, dict) else {})
    if this_call_cost == 0 and usage_md:
        logger.warning(
            "extract_summary: call_cost returned 0 for model=%r; usage_metadata=%r",
            _get_llm().model,
            usage_md,
        )

    # Always overwrite chunk_id from the input chunk — LLM may echo exemplar id.
    summary = Summary(
        chunk_id=chunk.chunk_id,
        beginning_balance=raw_result.beginning_balance,
        ending_balance=raw_result.ending_balance,
        deposits_total=raw_result.deposits_total,
        deposits_count=raw_result.deposits_count,
        withdrawals_total=raw_result.withdrawals_total,
        withdrawals_count=raw_result.withdrawals_count,
    )
    return {"summaries": [summary], "cumulative_cost_usd": this_call_cost}

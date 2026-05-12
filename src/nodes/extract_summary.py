"""``extract_summary`` graph node — extracts period monetary Summary per chunk.

Invoked once per ``PeriodChunk`` via LangGraph ``Send`` fan-out (wired in
``src/graph/builder.py``).  Uses Sonnet 4.6 with Anthropic prompt caching on
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


def _get_llm() -> Any:
    """Return (or create) the module-level ChatAnthropic singleton."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        from langchain_anthropic import ChatAnthropic

        _LLM_INSTANCE = ChatAnthropic(  # type: ignore[call-arg]
            model="claude-sonnet-4-6",
            max_tokens=4096,
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
    if len(raw_text) > _MAX_INPUT_CHARS:
        logger.warning(
            "extract_summary: chunk %s text is %d chars, truncating to %d",
            chunk.chunk_id,
            len(raw_text),
            _MAX_INPUT_CHARS,
        )
    text = raw_text[:_MAX_INPUT_CHARS]

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


def _invoke_llm(chunk: PeriodChunk, text: str) -> dict[str, Any]:
    """Call the LLM with prompt caching and return the state delta.

    The stable prompt prefix (everything before ``{chunk_text}``) is sent as a
    separate content block with ``cache_control: ephemeral`` so that the prefix
    is cached and reused across the 10-period fan-out.  The dynamic chunk text
    goes in a second content block WITHOUT cache_control.
    """
    from langchain_core.messages import SystemMessage

    prompt_body = load_prompt("extract_summary", version=1)
    stable_prefix, sep, _ = prompt_body.partition("{chunk_text}")
    if not sep:
        # Prompt file is malformed: missing placeholder. Use whole body as prefix.
        stable_prefix = prompt_body

    system = SystemMessage(
        content=[
            {
                "type": "text",
                "text": stable_prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": text,
            },
        ]
    )

    llm_with_output = _get_llm().with_structured_output(Summary)
    raw_result: Summary = llm_with_output.invoke([system])

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
    return {"summaries": [summary]}

"""``extract_account`` graph node — extracts Account per period chunk.

Invoked once per ``PeriodChunk`` via LangGraph ``Send`` fan-out (wired in
``src/graph/builder.py``).  Uses Sonnet 4.6 with Anthropic prompt caching on
the stable prompt prefix.

Never raises — on any recoverable error the node returns a placeholder Account
and appends a diagnostic to ``errors[]``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import anthropic
from pydantic import ValidationError

from src.api.logging import get_logger
from src.models import Account, Period, PeriodChunk
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

# Account / summary headers live in the first portion of the chunk text;
# truncate to keep token usage bounded.
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


def extract_account(chunk: PeriodChunk) -> dict[str, Any]:
    """Extract bank account information from *chunk* and return a state delta.

    Parameters
    ----------
    chunk:
        A single ``PeriodChunk`` dispatched via LangGraph ``Send``.

    Returns
    -------
    dict
        Always contains ``"accounts": [Account]``.  Contains ``"errors"``
        only when falling back to a placeholder Account.
    """
    # Prefer pdf_text; fall back to ocr_slice when pdf_text is empty.
    raw_text: str = chunk.pdf_text if chunk.pdf_text else (chunk.ocr_slice or "")
    if len(raw_text) > _MAX_INPUT_CHARS:
        logger.warning(
            "extract_account: chunk %s text is %d chars, truncating to %d",
            chunk.chunk_id,
            len(raw_text),
            _MAX_INPUT_CHARS,
        )
    text = raw_text[:_MAX_INPUT_CHARS]

    try:
        return _invoke_llm(chunk, text)
    except _RECOVERABLE_ERRORS as exc:
        hint = chunk.account_hint_last4 or "0000"
        placeholder = Account(
            chunk_id=chunk.chunk_id,
            bank="",
            account_last4=hint,
            period=Period(start=date(1970, 1, 1), end=date(1970, 1, 1)),
        )
        error_msg = (
            f"extract_account: {chunk.chunk_id} fell back to placeholder: "
            f"{exc.__class__.__name__}: {exc}"
        )
        logger.warning(error_msg)
        return {"accounts": [placeholder], "errors": [error_msg]}


def _invoke_llm(chunk: PeriodChunk, text: str) -> dict[str, Any]:
    """Call the LLM with prompt caching and return the state delta.

    The stable prompt prefix (everything before ``{chunk_text}``) is sent as a
    separate content block with ``cache_control: ephemeral`` so that the prefix
    is cached and reused across the 10-period fan-out.  The dynamic chunk text
    goes in a second content block WITHOUT cache_control.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_body = load_prompt("extract_account", version=1)
    stable_prefix, sep, _ = prompt_body.partition("{chunk_text}")
    if not sep:
        # Prompt file is malformed: missing placeholder. Use whole body as prefix.
        stable_prefix = prompt_body

    # Stable prefix → SystemMessage (cached).  Dynamic chunk → HumanMessage.
    # Anthropic requires ≥1 user message in the messages[] array; a
    # SystemMessage-only call returns 400 "messages: at least one message is required".
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

    llm_with_output = _get_llm().with_structured_output(Account)
    raw_result: Account = llm_with_output.invoke([system, user])

    # Always overwrite chunk_id from the input chunk — LLM may echo exemplar id.
    account = Account(
        chunk_id=chunk.chunk_id,
        bank=raw_result.bank,
        account_last4=raw_result.account_last4,
        period=raw_result.period,
    )
    return {"accounts": [account]}

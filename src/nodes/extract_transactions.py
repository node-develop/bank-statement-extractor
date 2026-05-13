"""``extract_transactions`` graph node — extracts Transaction list per chunk.

Invoked once per ``PeriodChunk`` via LangGraph ``Send`` fan-out (wired in
``src/graph/builder.py``).  Uses Sonnet 4.6 with Anthropic prompt caching on
the stable prompt prefix.

``with_structured_output`` does not accept a bare ``list[Transaction]`` as
schema.  A single-field container model (``_TransactionList``) is defined in
this module — it is intentionally NOT exported from ``src/models`` to keep
that namespace clean.

Never raises — on any recoverable error the node returns ``{"transactions": [],
"errors": [...]}`` and logs a WARNING.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal  # noqa: TC003 — runtime-required by Pydantic field annotations
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ValidationError, field_validator

from src.api.logging import get_logger
from src.api.pricing import call_cost
from src.models import PeriodChunk, Transaction
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
# LLM-facing schemas — defined here (not in src/models) to keep that namespace
# clean.  Stripping ``chunk_id`` from the row schema saves ~30 output tokens
# per row (≈ 5 760 tokens for Ixonia period_01 with 192 transactions).
# chunk_id is re-injected server-side after the LLM returns.
# ---------------------------------------------------------------------------


class _TransactionRow(BaseModel):
    """Single transaction row as the LLM sees it — no ``chunk_id``."""

    date: date
    description: str
    amount: Decimal  # non-negative; sign conveyed by ``direction``
    direction: Literal["credit", "debit"]
    running_balance: Decimal | None = None

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_iso_date(cls, v: object) -> object:
        """Accept ISO-8601 strings from LLM structured output."""
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v


class _TransactionList(BaseModel):
    """Single-field container so with_structured_output has a concrete schema."""

    transactions: list[_TransactionRow]


# ---------------------------------------------------------------------------
# Lazy singleton LLM — instantiated on first call so imports stay cheap and
# tests can monkeypatch ``_get_llm`` before the first invocation.
# ---------------------------------------------------------------------------
_LLM_INSTANCE: Any = None

# Transaction rows are spread across the entire chunk; do NOT truncate.
# Log a warning if the chunk is very large.
_WARN_CHARS = 80_000


def _get_llm() -> Any:
    """Return (or create) the module-level ChatAnthropic singleton."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        from langchain_anthropic import ChatAnthropic

        # max_tokens=20k — cap output cost (Sonnet @ $15/M output).
        # Empirical Ixonia worst case (period_06: 71+118=189 tx, period_02:
        # 95+142=237 tx) fits in ~18k output tokens with the stripped
        # _TransactionRow schema (no chunk_id; ~80 tok/row).  4096 was too
        # tight and produced silent truncation; 32k overpaid.  timeout=180s
        # remains for the longest periods.
        _LLM_INSTANCE = ChatAnthropic(  # type: ignore[call-arg]
            model="claude-sonnet-4-6",
            max_tokens=20_000,
            temperature=0,
            timeout=180,
        )
    return _LLM_INSTANCE


def extract_transactions(chunk: PeriodChunk) -> dict[str, Any]:
    """Extract the ordered transaction list from *chunk* and return a state delta.

    Parameters
    ----------
    chunk:
        A single ``PeriodChunk`` dispatched via LangGraph ``Send``.

    Returns
    -------
    dict
        Always contains ``"transactions": list[Transaction]``.  Contains
        ``"errors"`` only when the LLM call or validation fails.
    """
    # Source-selection policy: pdf_text is primary — split_periods aligns it
    # with chunk.page_range so every transaction page is visible to the LLM.
    # ocr_slice is the fallback only when pdf_text is empty or whitespace-only;
    # under the previous truthy-fallback a truncated-but-non-empty pdf_text
    # silently shadowed ocr_slice, which was the dominant cause of incomplete
    # extraction.
    if chunk.pdf_text and chunk.pdf_text.strip():
        raw_text = chunk.pdf_text
        source = "pdf_text"
    else:
        raw_text = chunk.ocr_slice or ""
        source = "ocr_slice_fallback"
    logger.info(
        "extract_transactions: %s using %s (%d chars)",
        chunk.chunk_id,
        source,
        len(raw_text),
    )
    if len(raw_text) > _WARN_CHARS:
        logger.warning(
            "extract_transactions: chunk %s text is %d chars (>%d); proceeding without truncation",
            chunk.chunk_id,
            len(raw_text),
            _WARN_CHARS,
        )

    try:
        return _invoke_llm(chunk, raw_text)
    except _RECOVERABLE_ERRORS as exc:
        error_msg = (
            f"extract_transactions: {chunk.chunk_id} fell back to empty list: "
            f"{exc.__class__.__name__}: {exc}"
        )
        logger.warning(error_msg)
        return {"transactions": [], "errors": [error_msg]}


def _invoke_llm(chunk: PeriodChunk, text: str) -> dict[str, Any]:
    """Call the LLM with prompt caching and return the state delta.

    The stable prompt prefix (everything before the dynamic tail that contains
    ``{chunk_id}``, ``{beginning_balance}``, and ``{chunk_text}``) is sent as a
    separate content block with ``cache_control: ephemeral`` so that the prefix
    is cached and reused across the 10-period fan-out.  The dynamic block goes
    in a second content block WITHOUT cache_control.

    ``beginning_balance`` is passed as the sentinel ``"unknown"``.
    The prompt instructs the model to use the running-balance-delta rule from
    the first printed balance when the sentinel is present.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_body = load_prompt("extract_transactions", version=1)

    # The dynamic tail starts at the ``{chunk_id}`` / ``{beginning_balance}``
    # / ``{chunk_text}`` section.  Partition on the last section header.
    dynamic_marker = "## Chunk to extract"
    stable_prefix, sep, _ = prompt_body.partition(dynamic_marker)
    if not sep:
        # Fallback: partition on {chunk_text} placeholder.
        stable_prefix, sep, _ = prompt_body.partition("{chunk_text}")
        if not sep:
            stable_prefix = prompt_body

    # Build the dynamic block: inject chunk_id, beginning_balance, then text.
    dynamic_text = f"chunk_id={chunk.chunk_id}\nbeginning_balance=unknown\n\n{text}"

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
    user = HumanMessage(content=dynamic_text)

    # include_raw=True → {"raw": AIMessage, "parsed": _TransactionList, "parsing_error": None}
    # so we can read usage_metadata for cost tracking.
    # Defensive: if a test mock returns the parsed model directly instead of
    # the include_raw dict, fall back gracefully — usage_metadata won't be
    # available and cost will be 0 for that call.
    llm_with_output = _get_llm().with_structured_output(_TransactionList, include_raw=True)
    invoke_result: Any = llm_with_output.invoke([system, user])
    if isinstance(invoke_result, dict):
        raw_msg = invoke_result.get("raw")
        raw_result: _TransactionList | None = invoke_result.get("parsed")
        parsing_error = invoke_result.get("parsing_error")
        if raw_result is None:
            raise ValueError(
                f"extract_transactions: structured-output parsed=None "
                f"(parsing_error={parsing_error!r})"
            )
    else:
        raw_msg = None
        raw_result = invoke_result

    # Cost tracking — read usage_metadata from the AIMessage.
    usage_md = getattr(raw_msg, "usage_metadata", None) or {}
    this_call_cost = call_cost(_get_llm().model, usage_md if isinstance(usage_md, dict) else {})
    if this_call_cost == 0 and usage_md:
        logger.warning(
            "extract_transactions: call_cost returned 0 for model=%r; usage_metadata=%r",
            _get_llm().model,
            usage_md,
        )

    # Inject chunk_id server-side — it is absent from _TransactionRow (LLM schema).
    tx_list = [
        Transaction(chunk_id=chunk.chunk_id, **row.model_dump()) for row in raw_result.transactions
    ]
    return {"transactions": tx_list, "cumulative_cost_usd": this_call_cost}

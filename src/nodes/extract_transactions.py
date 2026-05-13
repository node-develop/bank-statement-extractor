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

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from src.api.logging import get_logger
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
# Container model — wraps list[Transaction] for with_structured_output.
# Defined here (not in src/models) to keep that namespace clean.
# ---------------------------------------------------------------------------


class _TransactionList(BaseModel):
    """Single-field container so with_structured_output has a concrete schema."""

    transactions: list[Transaction]


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

        _LLM_INSTANCE = ChatAnthropic(  # type: ignore[call-arg]
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0,
            timeout=60,
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
    # Prefer pdf_text; fall back to ocr_slice when pdf_text is empty.
    # Do NOT truncate — transaction rows span the full chunk.
    raw_text: str = chunk.pdf_text if chunk.pdf_text else (chunk.ocr_slice or "")
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

    ``beginning_balance`` is passed as the sentinel ``"unknown"`` at M2 R2.
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

    llm_with_output = _get_llm().with_structured_output(_TransactionList)
    raw_result: _TransactionList = llm_with_output.invoke([system, user])

    # Always overwrite chunk_id on every transaction from the input chunk.
    tx_list = [
        Transaction(
            chunk_id=chunk.chunk_id,
            date=tx.date,
            description=tx.description,
            amount=tx.amount,
            direction=tx.direction,
            running_balance=tx.running_balance,
        )
        for tx in raw_result.transactions
    ]
    return {"transactions": tx_list}

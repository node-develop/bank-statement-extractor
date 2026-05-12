"""``classify_layout`` graph node — LLM-based layout classifier per chunk.

Invoked once per ``PeriodChunk`` via LangGraph ``Send`` fan-out (wired in
``src/graph/builder.py``).  Uses Haiku 4.5 with Anthropic prompt caching on
the stable prompt prefix.

Never raises — on any LLM or validation error the node returns
``label="unknown"`` and appends a diagnostic to ``errors[]``.
"""

from __future__ import annotations

from typing import Any

import anthropic
from pydantic import ValidationError

from src.api.logging import get_logger
from src.models import LayoutLabel, PeriodChunk
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

_MAX_INPUT_CHARS = 2_000  # layout markers live in the header; truncate the rest


def _get_llm() -> Any:
    """Return (or create) the module-level ChatAnthropic singleton."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        from langchain_anthropic import ChatAnthropic

        _LLM_INSTANCE = ChatAnthropic(  # type: ignore[call-arg]
            model="claude-haiku-4-5",
            max_tokens=512,
            temperature=0,
            timeout=20,
        )
    return _LLM_INSTANCE


def classify_layout(chunk: PeriodChunk) -> dict[str, Any]:
    """Classify the layout of *chunk* and return a partial state delta.

    Parameters
    ----------
    chunk:
        A single ``PeriodChunk`` dispatched via LangGraph ``Send``.

    Returns
    -------
    dict
        Always contains ``"layouts": [LayoutLabel]``.  Contains ``"errors"``
        only when falling back to ``"unknown"``.
    """
    # Prefer pdf_text; fall back to ocr_slice if pdf_text is empty.
    raw_text: str = chunk.pdf_text if chunk.pdf_text else (chunk.ocr_slice or "")
    text = raw_text[:_MAX_INPUT_CHARS]

    try:
        return _invoke_llm(chunk, text)
    except _RECOVERABLE_ERRORS as exc:
        label = LayoutLabel(chunk_id=chunk.chunk_id, label="unknown")
        error_msg = (
            f"classify_layout: {chunk.chunk_id} fell back to 'unknown': "
            f"{exc.__class__.__name__}: {exc}"
        )
        logger.warning(error_msg)
        _tag_run_unknown_layout()
        return {"layouts": [label], "errors": [error_msg]}


def _tag_run_unknown_layout() -> None:
    """Tag the active LangSmith run with ``unknown_layout``.

    Soft requirement (architecture.md Error model): when classify_layout
    emits ``unknown``, the run should be tagged so the trace is searchable.
    No-op when LangSmith is not active (e.g. unit tests).
    """
    try:
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:
        return
    run = get_current_run_tree()
    if run is None:
        return
    existing = list(run.tags or [])
    if "unknown_layout" not in existing:
        run.tags = [*existing, "unknown_layout"]


def _invoke_llm(chunk: PeriodChunk, text: str) -> dict[str, Any]:
    """Call the LLM with prompt caching and return the state delta.

    The stable prompt prefix (everything before ``{chunk_text}``) is sent as a
    separate content block with ``cache_control: ephemeral`` so that the prefix
    is cached and reused across the 10-period fan-out (architecture.md "Shared
    system prompt uses Anthropic prompt caching").  The dynamic chunk text goes
    in a second content block WITHOUT cache_control, so it doesn't poison the
    cache key.
    """
    from langchain_core.messages import SystemMessage

    prompt_body = load_prompt("classify_layout", version=1)
    stable_prefix, sep, _ = prompt_body.partition("{chunk_text}")
    if not sep:
        # Prompt file is malformed: missing placeholder. Fall back to a single
        # uncached block so behavior is correct even if caching is sub-optimal.
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

    llm_with_output = _get_llm().with_structured_output(LayoutLabel)
    raw_result: LayoutLabel = llm_with_output.invoke([system])

    # Always overwrite chunk_id from the input chunk — the LLM output's
    # chunk_id is unreliable because the model may echo the exemplar id.
    label = LayoutLabel(chunk_id=chunk.chunk_id, label=raw_result.label)
    return {"layouts": [label]}

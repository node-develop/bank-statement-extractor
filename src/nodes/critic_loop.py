"""``critic`` graph node + routing helpers — emit a ``CriticHint`` on reconciliation failure.

M2 R3 scope
-----------
The critic node runs **once** per graph execution when any ``Reconciliation``
has ``reconciled=False``.  It calls Haiku 4.5 with the reconciliation failure
context, records the hint in ``state["errors"]``, and increments
``retry_count``.

M3 will wire the actual extractor retry by reading ``pending_hint`` and
re-dispatching to the relevant extractor node.  In this milestone, the hint is
recorded but the extractor is NOT re-invoked.

Design decisions
----------------
- ``CriticHint`` is internal to this module; the spec requires it is NOT
  exported from ``src/models``.
- ``_RECOVERABLE`` covers all expected failure modes: Anthropic API errors,
  Pydantic validation failures, and Python structural errors.  On any of these
  the node still bumps ``retry_count`` so the graph exits cleanly on the next
  ``should_run_critic`` check.
- The prompt is loaded from ``src/prompts/critic.md`` via ``load_prompt``.
  The stable prefix (everything before ``## Reconciliation failure``) is sent
  with ``cache_control: ephemeral``; the dynamic failure context is sent as a
  separate uncached block.
- ``should_run_critic`` is the conditional-edge router read by ``builder.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import anthropic
from pydantic import BaseModel, ValidationError

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.prompts import load_prompt

if TYPE_CHECKING:
    from src.models import Reconciliation

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# CriticHint — internal schema (NOT exported from src/models)
# ---------------------------------------------------------------------------


class CriticHint(BaseModel):
    """One actionable retry suggestion produced by the critic LLM."""

    chunk_id: str
    extractor: Literal["extract_account", "extract_summary", "extract_transactions"]
    hint: str


# ---------------------------------------------------------------------------
# Recoverable exception tuple (rule: no bare except)
# ---------------------------------------------------------------------------

_RECOVERABLE = (
    anthropic.APIError,
    ValidationError,
    KeyError,
    TypeError,
    ValueError,
)

# ---------------------------------------------------------------------------
# Lazy singleton LLM
# ---------------------------------------------------------------------------

_LLM_INSTANCE: Any = None


def _get_llm() -> Any:
    """Return (or create) the module-level Haiku ChatAnthropic singleton."""
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


# ---------------------------------------------------------------------------
# Public node
# ---------------------------------------------------------------------------


def critic(state: GraphState) -> dict[str, Any]:
    """Diagnose the first un-reconciled chunk and record a hint in ``errors[]``.

    Parameters
    ----------
    state:
        Full ``GraphState`` after ``reconcile`` has run.

    Returns
    -------
    dict
        Always contains ``"retry_count"``.
        Contains ``"errors"`` with the hint string (success path) or an error
        note (failure path).
        Contains ``"pending_hint"`` (a ``CriticHint``) on the success path.

    Notes
    -----
    This node **never raises** — all recoverable failures are captured in
    ``errors[]`` so the graph can continue to ``finalize``.
    """
    reconciliations = state.get("reconciliations", [])
    current_retry = state.get("retry_count", 0)

    # Belt-and-braces: if all are reconciled, do nothing.
    failed = [r for r in reconciliations if not r.reconciled]
    if not failed:
        logger.info("critic: all periods reconciled — nothing to do")
        return {"errors": ["critic invoked but all periods reconciled"]}

    target_rec = failed[0]
    chunk_id = target_rec.chunk_id

    logger.info(
        "critic: analysing chunk_id=%s delta=%s retry_count=%d",
        chunk_id,
        target_rec.delta,
        current_retry,
    )

    try:
        hint = _invoke_critic_llm(state, target_rec)
        hint_str = f"critic suggested: rerun {hint.extractor} on {hint.chunk_id} -- {hint.hint}"
        logger.info("critic: %s", hint_str)
        return {
            "retry_count": current_retry + 1,
            "pending_hint": hint,
            "errors": [hint_str],
        }
    except _RECOVERABLE as exc:
        error_msg = (
            f"critic: failed to produce hint for {chunk_id}: {exc.__class__.__name__}: {exc}"
        )
        logger.warning(error_msg)
        return {
            "retry_count": current_retry + 1,
            "errors": [error_msg],
        }


# ---------------------------------------------------------------------------
# Conditional-edge router
# ---------------------------------------------------------------------------


def should_run_critic(state: GraphState) -> str:
    """Routing function for the conditional edge after ``reconcile``.

    Returns
    -------
    str
        ``"critic"`` when there is at least one un-reconciled period AND
        ``retry_count < 2``.
        ``"finalize"`` otherwise.
    """
    reconciliations = state.get("reconciliations", [])
    has_failure = any(not r.reconciled for r in reconciliations)
    retry_count = state.get("retry_count", 0)

    if has_failure and retry_count < 2:
        logger.info("should_run_critic: routing to critic (retry_count=%d)", retry_count)
        return "critic"

    logger.info(
        "should_run_critic: routing to finalize (has_failure=%s, retry_count=%d)",
        has_failure,
        retry_count,
    )
    return "finalize"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _invoke_critic_llm(
    state: GraphState,
    rec: Reconciliation,
) -> CriticHint:
    """Call Haiku 4.5 and parse the structured ``CriticHint`` response.

    Two-block prompt pattern (architecture.md):
    - Block 1 (stable prefix, cache_control ephemeral): everything before the
      ``## Reconciliation failure`` section in critic.md.
    - Block 2 (dynamic, no cache): the serialised failure context.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_body = load_prompt("critic", version=1)

    # Split on the dynamic placeholder section
    stable_prefix, sep, _ = prompt_body.partition("## Reconciliation failure")
    if not sep:
        # Malformed prompt: use whole body as stable prefix.
        stable_prefix = prompt_body

    # Build dynamic failure context
    chunk_id = rec.chunk_id
    summaries = state.get("summaries", [])
    transactions = state.get("transactions", [])

    summary = next((s for s in summaries if s.chunk_id == chunk_id), None)
    chunk_txs = [t for t in transactions if t.chunk_id == chunk_id]
    tx_count = len(chunk_txs)

    summary_json = summary.model_dump_json() if summary is not None else "null"
    notes_joined = "\n".join(f"- {n}" for n in rec.notes) if rec.notes else "(none)"

    dynamic_block = (
        f"## Reconciliation failure for chunk {chunk_id}\n\n"
        f"Summary: {summary_json}\n"
        f"Transactions count={tx_count}\n"
        f"Delta={rec.delta}\n"
        f"{notes_joined}"
    )

    # Stable prefix → SystemMessage (cached).  Dynamic block → HumanMessage
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
    user = HumanMessage(content=dynamic_block)

    llm_with_output = _get_llm().with_structured_output(CriticHint)
    result: CriticHint = llm_with_output.invoke([system, user])

    # Ensure chunk_id is propagated from the failure context, not the LLM echo.
    return CriticHint(
        chunk_id=chunk_id,
        extractor=result.extractor,
        hint=result.hint,
    )

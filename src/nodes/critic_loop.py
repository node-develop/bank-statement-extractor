"""``critic`` graph node + routing helpers — Phase 3 rewrite.

Phase 3 changes (PRD §4.2.1)
-----------------------------
The critic node now consumes ``state["verifier_reports"]`` instead of
``state["reconciliations"]``.  In the new topology, reconciliation has NOT
run yet when ``critic`` is invoked (verifier precedes reconcile); the old
behaviour that early-returned on empty ``reconciliations`` would silently
no-op.

``route_after_verifier`` (NEW) is the conditional-edge router placed after
``verifier``.  It replaces ``should_run_critic`` as the primary routing
function; ``should_run_critic`` is kept for backward-compatibility but is
marked deprecated.

``apply_critic_hint`` is a separate node in ``src/nodes/apply_critic_hint.py``
(PRD §4.2.2).

Design decisions (unchanged from M2)
-------------------------------------
- ``CriticHint`` is internal to this module; NOT exported from ``src/models``.
- ``_RECOVERABLE`` covers all expected failure modes.
- The prompt is loaded from ``src/prompts/critic.md`` via ``load_prompt``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

import anthropic
from pydantic import BaseModel, ValidationError

from src.api.logging import get_logger
from src.api.pricing import call_cost
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.prompts import load_prompt

if TYPE_CHECKING:
    from src.models import VerifierReport

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
# Public routing function (Phase 3)
# ---------------------------------------------------------------------------


def route_after_verifier(state: GraphState) -> str:
    """Route after ``verifier``: reconcile (clean), critic (1-3 suspects, retries left),
    or await_review (cost-cap | many suspects | retry exhausted).

    Parameters
    ----------
    state:
        Full ``GraphState`` after ``verifier`` has populated
        ``state["verifier_reports"]``.

    Returns
    -------
    str
        One of ``"reconcile"``, ``"critic"``, or ``"await_review"``.
    """
    import os

    from src.api.pricing import HARD_COST_CAP_USD

    reports = state.get("verifier_reports", [])
    total_suspects = sum(len(r.suspects) for r in reports)
    retry = state.get("retry_count", 0)
    cost_capped = state.get("cumulative_cost_usd", Decimal("0")) >= HARD_COST_CAP_USD

    # Hard threshold for routing straight to await_review (HITL).  Default 3
    # is the production setting; override via env to test the HITL path on
    # any fixture (BSA_AWAIT_REVIEW_SUSPECTS=0 makes ANY non-clean run pause).
    try:
        suspects_threshold = int(os.environ.get("BSA_AWAIT_REVIEW_SUSPECTS", "3"))
    except ValueError:
        suspects_threshold = 3

    if total_suspects == 0 and not cost_capped:
        logger.info("route_after_verifier: clean — routing to reconcile")
        return "reconcile"
    if cost_capped or total_suspects > suspects_threshold or retry >= 2:
        logger.info(
            "route_after_verifier: routing to await_review "
            "(cost_capped=%s, total_suspects=%d, retry=%d)",
            cost_capped,
            total_suspects,
            retry,
        )
        return "await_review"
    logger.info(
        "route_after_verifier: routing to critic (total_suspects=%d, retry=%d)",
        total_suspects,
        retry,
    )
    return "critic"


# ---------------------------------------------------------------------------
# Public node (Phase 3 rewrite)
# ---------------------------------------------------------------------------


def critic(state: GraphState) -> dict[str, Any]:
    """Diagnose the first verifier-flagged chunk and emit a ``CriticHint``.

    Phase 3: reads ``state["verifier_reports"]`` instead of
    ``state["reconciliations"]`` (reconcile has not run yet in the new
    topology).

    Parameters
    ----------
    state:
        Full ``GraphState`` after ``verifier`` has run.

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
    ``errors[]`` so the graph can continue.
    """
    reports_with_suspects: list[VerifierReport] = [
        r for r in state.get("verifier_reports", []) if r.suspects
    ]
    current_retry = state.get("retry_count", 0)

    if not reports_with_suspects:
        logger.info("critic: no verifier suspects — nothing to do")
        return {"errors": ["critic invoked but no verifier suspects"]}

    target_report = reports_with_suspects[0]
    chunk_id = target_report.chunk_id

    logger.info(
        "critic: analysing chunk_id=%s suspects=%d retry_count=%d",
        chunk_id,
        len(target_report.suspects),
        current_retry,
    )

    try:
        hint, this_call_cost = _invoke_critic_llm(state, target_report)
        hint_str = f"Critic re-ran {hint.extractor} on {hint.chunk_id}: {hint.hint}"
        logger.info("critic: %s", hint_str)
        # The critic's diagnostic is INFORMATIONAL — it tells the user that
        # a retry happened and why. Goes to notes[], not errors[].
        return {
            "retry_count": current_retry + 1,
            "pending_hint": hint,
            "notes": [hint_str],
            "cumulative_cost_usd": this_call_cost,
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
# Deprecated conditional-edge router (kept for backward compatibility)
# ---------------------------------------------------------------------------


def should_run_critic(state: GraphState) -> str:
    """DEPRECATED — superseded by ``route_after_verifier`` in Phase 3.

    Kept to avoid import errors in any test or code that still references it.
    In the new topology (Phase 3), this function is no longer wired into the
    graph; ``route_after_verifier`` is the active router after ``verifier``.

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
        logger.info(
            "should_run_critic (deprecated): routing to critic (retry_count=%d)", retry_count
        )
        return "critic"

    logger.info(
        "should_run_critic (deprecated): routing to finalize (has_failure=%s, retry_count=%d)",
        has_failure,
        retry_count,
    )
    return "finalize"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _invoke_critic_llm(
    state: GraphState,
    report: VerifierReport,
) -> tuple[CriticHint, Decimal]:
    """Call Haiku 4.5 with verifier-suspect context and parse the ``CriticHint``.

    Returns
    -------
    tuple[CriticHint, Decimal]
        The parsed hint and the USD cost of this LLM call.

    Two-block prompt pattern (architecture.md):
    - Block 1 (stable prefix, cache_control ephemeral): everything before the
      ``## Reconciliation failure`` section in critic.md.
    - Block 2 (dynamic, no cache): the serialised suspect context.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_body = load_prompt("critic", version=1)

    # Split on the dynamic placeholder section
    stable_prefix, sep, _ = prompt_body.partition("## Reconciliation failure")
    if not sep:
        # Malformed prompt: use whole body as stable prefix.
        stable_prefix = prompt_body

    chunk_id = report.chunk_id
    summaries = state.get("summaries", [])
    transactions = state.get("transactions", [])

    summary = next((s for s in summaries if s.chunk_id == chunk_id), None)
    chunk_txs = [t for t in transactions if t.chunk_id == chunk_id]
    tx_count = len(chunk_txs)

    summary_json = summary.model_dump_json() if summary is not None else "null"

    # Format first ~5 suspects for the dynamic block
    suspect_lines = []
    for s in report.suspects[:5]:
        line = f"- [{s.code}] row {s.row_index}: {s.reason}"
        if s.expected is not None:
            line += f" (expected={s.expected}, actual={s.actual})"
        suspect_lines.append(line)
    suspects_str = "\n".join(suspect_lines) if suspect_lines else "(none)"

    dynamic_block = (
        f"## Reconciliation failure for chunk {chunk_id}\n\n"
        f"Summary: {summary_json}\n"
        f"Transactions count={tx_count}\n"
        f"Verifier suspects ({len(report.suspects)} total):\n"
        f"{suspects_str}"
    )

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

    # include_raw=True → {"raw": AIMessage, "parsed": CriticHint, "parsing_error": None}
    # so we can read usage_metadata for cost tracking (PRD §8.2).
    # Defensive: test mocks may return the parsed model directly — fall back.
    llm_with_output = _get_llm().with_structured_output(CriticHint, include_raw=True)
    invoke_result: Any = llm_with_output.invoke([system, user])
    if isinstance(invoke_result, dict):
        raw_msg = invoke_result.get("raw")
        result: CriticHint | None = invoke_result.get("parsed")
        parsing_error = invoke_result.get("parsing_error")
        if result is None:
            raise ValueError(
                f"critic: structured-output parsed=None (parsing_error={parsing_error!r})"
            )
    else:
        raw_msg = None
        result = invoke_result

    # Cost tracking.
    usage_md = getattr(raw_msg, "usage_metadata", None) or {}
    this_call_cost = call_cost(_get_llm().model, usage_md if isinstance(usage_md, dict) else {})
    if this_call_cost == 0 and usage_md:
        logger.warning(
            "critic: call_cost returned 0 for model=%r; usage_metadata=%r",
            _get_llm().model,
            usage_md,
        )

    # Ensure chunk_id is propagated from the failure context, not the LLM echo.
    hint = CriticHint(
        chunk_id=chunk_id,
        extractor=result.extractor,
        hint=result.hint,
    )
    return hint, this_call_cost

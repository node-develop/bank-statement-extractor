"""Graph builder for the bank-statement-analizer extraction pipeline.

Topology (architecture.md — Phase 3)
--------------------------------------
::

    START
      → ingest
      → split_periods
      → [Send per PeriodChunk x 4 extractors]
           → classify_layout  ─┐
           → extract_account   ├─→ merge_state → verifier
           → extract_summary   │                     │
           → extract_transactions ─┘        route_after_verifier
                                            ├── reconcile → finalize → END
                                            ├── critic → apply_critic_hint
                                            │               → [Send] → merge_state (loop)
                                            └── await_review → finalize → END

Fan-out
-------
``split_periods`` feeds a conditional edge ``_fan_out`` that returns one
``Send("classify_layout", chunk)``, ``Send("extract_account", chunk)``,
``Send("extract_summary", chunk)``, and ``Send("extract_transactions", chunk)``
per ``PeriodChunk``.  LangGraph's ``Send`` API dispatches each branch with the
chunk as its *entire* input state — the node receives a ``PeriodChunk``, not a
``GraphState``.

Join
----
All four extractor/classifier nodes have a direct edge to ``merge_state``.
LangGraph waits for all parallel branches to complete before running
``merge_state`` because it is the single downstream sink for each of those
edges.

Verifier + routing
------------------
After ``merge_state``, ``verifier`` runs deterministic C1-C6 checks and
populates ``verifier_reports``.  ``route_after_verifier`` then decides:
- ``"reconcile"`` — all reports have confidence==1.0 and cost not capped.
- ``"critic"``    — 1-3 suspects, retry_count < 2.
- ``"await_review"`` — cost cap hit, >3 suspects, or retry exhausted.

Critic retry loop
-----------------
After ``critic`` emits a ``CriticHint``, ``apply_critic_hint`` turns it into
a ``Send`` re-running one extractor for one chunk.  The re-run result flows
back through ``merge_state → verifier → route_after_verifier``.
``retry_count`` is bumped each pass; ``route_after_verifier`` caps at 2.

Cost ceiling
------------
``cumulative_cost_usd`` (Annotated[Decimal, _add_decimal] in GraphState)
accumulates per-call cost deltas returned by every LLM-using node.  When
the total reaches ``HARD_COST_CAP_USD`` (default $5.00, overridable via
``BSA_COST_CAP_USD`` env var), ``route_after_verifier`` routes to
``await_review`` regardless of suspect count.

LangGraph API notes (confirmed via context7)
--------------------------------------------
- ``Send`` is imported from ``langgraph.types``.
- ``add_conditional_edges("node", fn)`` where ``fn`` returns a list of
  ``Send`` objects is the documented map-reduce pattern.
- ``graph.compile(checkpointer=saver)`` — checkpointer is optional; omit the
  kwarg entirely when ``None`` to avoid passing ``None`` to the underlying
  pydantic schema.
- ``recursion_limit`` is set in the invoke ``config`` dict, not at compile
  time.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.api.logging import get_logger
from src.graph.state import GraphState
from src.nodes.apply_critic_hint import apply_critic_hint
from src.nodes.apply_human_corrections import apply_human_corrections
from src.nodes.await_review import await_review
from src.nodes.classify_layout import classify_layout
from src.nodes.critic_loop import critic, route_after_verifier, should_run_critic
from src.nodes.extract_account import extract_account
from src.nodes.extract_summary import extract_summary
from src.nodes.extract_transactions import extract_transactions
from src.nodes.finalize import finalize
from src.nodes.ingest import ingest
from src.nodes.merge_state import merge_state
from src.nodes.reconcile import reconcile
from src.nodes.split_periods import split_periods
from src.nodes.verifier import verifier

if TYPE_CHECKING:
    from src.models import ExtractResult, PeriodChunk

# Keep should_run_critic imported so existing code that references it via
# builder doesn't break; it is no longer wired into the graph.
__all__ = ["build_graph", "run_extract", "should_run_critic"]

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Fan-out function - returns Send objects, one per chunk x extractor
# ---------------------------------------------------------------------------


def _fan_out(state: GraphState) -> list[Send]:
    """Dispatch one Send per (chunk, extractor) pair after split_periods.

    LangGraph invokes each Send as an independent branch; the receiving node
    gets the ``PeriodChunk`` as its full input state (not the ``GraphState``).
    All four branches per chunk run in parallel.
    """
    chunks: list[PeriodChunk] = state["period_chunks"]
    sends: list[Send] = []
    for chunk in chunks:
        sends.append(Send("classify_layout", chunk))
        sends.append(Send("extract_account", chunk))
        sends.append(Send("extract_summary", chunk))
        sends.append(Send("extract_transactions", chunk))
    logger.info("_fan_out: dispatching %d Send objects for %d chunks", len(sends), len(chunks))
    return sends


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_graph(checkpointer: object | None = None) -> Any:
    """Compile and return the extraction ``StateGraph``.

    Parameters
    ----------
    checkpointer:
        An initialised ``BaseCheckpointSaver`` (e.g. ``SqliteSaver``).
        Pass ``None`` (default) for stateless execution (no persistence).

    Returns
    -------
    CompiledStateGraph
        Ready to call ``.invoke()`` or ``.stream()`` on.
    """
    graph = StateGraph(GraphState)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    graph.add_node("ingest", ingest)
    graph.add_node("split_periods", split_periods)
    # Per-chunk extractors receive a PeriodChunk via Send; their signatures
    # don't match LangGraph's TypedDict-state node signature in strict-mypy.
    graph.add_node("classify_layout", classify_layout)  # type: ignore[arg-type]
    graph.add_node("extract_account", extract_account)  # type: ignore[arg-type]
    graph.add_node("extract_summary", extract_summary)  # type: ignore[arg-type]
    graph.add_node("extract_transactions", extract_transactions)  # type: ignore[arg-type]
    graph.add_node("merge_state", merge_state)
    graph.add_node("verifier", verifier)
    graph.add_node("reconcile", reconcile)
    graph.add_node("critic", critic)
    graph.add_node("apply_critic_hint", apply_critic_hint)
    graph.add_node("await_review", await_review)
    graph.add_node("finalize", finalize)

    # ------------------------------------------------------------------
    # Linear backbone edges
    # ------------------------------------------------------------------
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "split_periods")

    # ------------------------------------------------------------------
    # Fan-out: split_periods -> [Send per chunk x 4 nodes]
    # Confirmed API: add_conditional_edges with a function returning
    # list[Send] is the documented map-reduce pattern (context7).
    # ------------------------------------------------------------------
    graph.add_conditional_edges(
        "split_periods",
        _fan_out,
        ["classify_layout", "extract_account", "extract_summary", "extract_transactions"],
    )

    # ------------------------------------------------------------------
    # Join: all extractor branches → merge_state
    # LangGraph waits for all branches completing before merge_state runs.
    # ------------------------------------------------------------------
    graph.add_edge("classify_layout", "merge_state")
    graph.add_edge("extract_account", "merge_state")
    graph.add_edge("extract_summary", "merge_state")
    graph.add_edge("extract_transactions", "merge_state")

    # ------------------------------------------------------------------
    # Post-join: merge_state → verifier → conditional routing
    # ------------------------------------------------------------------
    graph.add_edge("merge_state", "verifier")
    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {"reconcile": "reconcile", "critic": "critic", "await_review": "await_review"},
    )

    # ------------------------------------------------------------------
    # Happy path: reconcile → finalize
    # ------------------------------------------------------------------
    graph.add_edge("reconcile", "finalize")

    # ------------------------------------------------------------------
    # Critic retry loop:
    # critic → apply_critic_hint (Send fan-out) → extractor → merge_state (loop)
    # apply_critic_hint returns list[Send] targeting one of the extract_* nodes.
    # ------------------------------------------------------------------
    graph.add_conditional_edges(
        "critic",
        apply_critic_hint,
        ["extract_account", "extract_summary", "extract_transactions"],
    )

    # ------------------------------------------------------------------
    # HITL path (Phase 4): await_review →
    #   - force_resume=True OR no corrections → "finalize"
    #   - corrections present → list[Send] dispatching extract_transactions
    # Mirrors the ``critic → apply_critic_hint`` pattern: the helper is used
    # ONLY as the routing function (not registered as a node), so its
    # ``list[Send]`` return value is consumed by ``add_conditional_edges``
    # rather than being treated as a state delta dict (which would be a
    # silent re-execution bug).
    # ------------------------------------------------------------------
    def _route_after_review(state: GraphState) -> str | list[Send]:
        if state.get("force_resume"):
            return "finalize"
        sends = apply_human_corrections(state)
        if not sends:
            return "finalize"
        return sends

    graph.add_conditional_edges(
        "await_review",
        _route_after_review,
        ["finalize", "extract_transactions"],
    )

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------
    graph.add_edge("finalize", END)

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------
    if checkpointer is not None:
        # build_checkpointer() returns object (sqlite/postgres/memory saver) —
        # all are BaseCheckpointSaver in practice. Type stubs widen to object.
        compiled = graph.compile(checkpointer=checkpointer)  # type: ignore[arg-type]
    else:
        compiled = graph.compile()

    logger.info("build_graph: compiled extraction graph (Phase 3 topology)")
    return compiled


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def run_extract(pdf_path: str, txt_path: str | None = None) -> ExtractResult:
    """Build the graph, invoke it, and return the ``ExtractResult``.

    This wrapper handles checkpointer lifecycle automatically.  For long-lived
    processes (FastAPI) use ``build_graph(checkpointer=saver)`` directly and
    manage the saver lifecycle in the lifespan context.

    Parameters
    ----------
    pdf_path:
        Absolute path to the PDF file to extract.
    txt_path:
        Optional absolute path to the companion OCR text file.

    Returns
    -------
    ExtractResult
        The assembled extraction result including all periods and reconciliation
        status.

    Raises
    ------
    RuntimeError
        When ``state["final"]`` is absent after graph completion — indicates a
        topology bug (finalize was not reached).
    """
    from src.graph.checkpointer import build_checkpointer

    saver, teardown = build_checkpointer()
    try:
        compiled = build_graph(checkpointer=saver)
        thread_id = str(uuid.uuid4())
        initial_state: dict[str, Any] = {
            "pdf_path": pdf_path,
            "txt_path": txt_path,
            "layouts": [],
            "accounts": [],
            "summaries": [],
            "transactions": [],
            "reconciliations": [],
            "verifier_reports": [],
            "retry_count": 0,
            "errors": [],
            "cumulative_cost_usd": Decimal("0"),
        }
        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 50,
        }
        result_state: GraphState = compiled.invoke(initial_state, config=config)

        if "final" not in result_state:
            raise RuntimeError(
                "run_extract: graph completed without populating state['final']. "
                "Check that 'finalize' node was reached."
            )
        return result_state["final"]
    finally:
        teardown()

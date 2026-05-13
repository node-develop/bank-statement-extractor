"""SSE event generator over a single ``graph.astream_events`` invocation.

Phase 4 of `docs/superpowers/specs/2026-05-13-frontend-redesign-design.md`.

Pure async generator: no FastAPI, no HTTP. The router in
`src/api/routers/extract_stream.py` wraps these dicts into
``data: {json}\\n\\n`` lines.

Cost attribution is by **model name** (from each AIMessage's
``response_metadata.model_name``), not by graph-node name — LangGraph
1.x does not auto-inject a ``langgraph:node=<name>`` tag (see
``docs/architecture.md`` §"SSE event mapping").

Server-side fan-out aggregation collapses ``Send``-fanned branches of
a step (e.g. 10 parallel ``extract_account`` invocations on Ixonia)
into one ``state:"running"`` + one ``state:"done"`` event per lane.
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.api.pricing import call_cost

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# 8 happy-path steps shown in the live timeline.
KNOWN_STEPS: frozenset[str] = frozenset(
    {
        "ingest",
        "split_periods",
        "classify_layout",
        "extract_account",
        "extract_summary",
        "extract_transactions",
        "verifier",
        "reconcile",
    }
)
# Side-graph nodes shown as a secondary indicator on the frontend.
SIDE_STEPS: frozenset[str] = frozenset(
    {"merge_state", "critic", "apply_critic_hint", "await_review", "finalize"}
)


def _ts_ms() -> int:
    return int(time.monotonic() * 1000)


def _model_and_usage(ev: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Pull model name + usage_metadata from an on_chat_model_end event."""
    out = (ev.get("data") or {}).get("output")
    if out is None:
        return ("", None)
    usage = getattr(out, "usage_metadata", None)
    if not isinstance(usage, dict):
        usage = None
    rm = getattr(out, "response_metadata", None) or {}
    model = ""
    if isinstance(rm, dict):
        model = rm.get("model_name") or rm.get("model") or ""
    return (model, usage if usage else None)


def _final_from_event(ev: dict[str, Any]) -> Any:
    """Extract the ``final`` ExtractResult from a ``finalize`` on_chain_end event."""
    out = (ev.get("data") or {}).get("output")
    if isinstance(out, dict):
        return out.get("final")
    return None


def _serialize_final(final: Any) -> dict[str, Any] | None:
    """Convert an ExtractResult (or dict) to a JSON-serialisable dict."""
    if final is None:
        return None
    if hasattr(final, "model_dump"):
        dumped: dict[str, Any] = final.model_dump(mode="json")
        return dumped
    if isinstance(final, dict):
        return final
    return None


def _period_states_from_reconcile(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit kind:"period" success/danger off reconciliation reducer output."""
    # Reconcile reducer adds entries to state["reconciliations"]; the on_chain_end
    # output for the reconcile NODE is the per-call delta, which is one
    # Reconciliation. Inspect both shapes defensively.
    out = (ev.get("data") or {}).get("output") or {}
    recs: list[Any] = []
    if isinstance(out, dict):
        recs = out.get("reconciliations") or []
    msgs: list[dict[str, Any]] = []
    for r in recs:
        chunk_id = getattr(r, "chunk_id", None) or (
            r.get("chunk_id") if isinstance(r, dict) else None
        )
        reconciled = getattr(r, "reconciled", None)
        if reconciled is None and isinstance(r, dict):
            reconciled = r.get("reconciled", False)
        if chunk_id is None:
            continue
        msgs.append(
            {
                "kind": "period",
                "chunk_id": chunk_id,
                "state": "success" if reconciled else "danger",
            }
        )
    return msgs


def _period_states_from_verifier(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit kind:"period" events for verifier output (suspects > 0 → danger)."""
    out = (ev.get("data") or {}).get("output") or {}
    reports: list[Any] = []
    if isinstance(out, dict):
        reports = out.get("verifier_reports") or []
    msgs: list[dict[str, Any]] = []
    for r in reports:
        chunk_id = getattr(r, "chunk_id", None) or (
            r.get("chunk_id") if isinstance(r, dict) else None
        )
        if chunk_id is None:
            continue
        suspects = getattr(r, "suspects", None) or (
            r.get("suspects") if isinstance(r, dict) else []
        )
        msgs.append(
            {
                "kind": "period",
                "chunk_id": chunk_id,
                "state": "danger" if suspects else "running",
            }
        )
    return msgs


async def stream_graph_events(
    graph: Any,
    initial_state: dict[str, Any],
    config: dict[str, Any],
) -> AsyncGenerator[dict[str, Any]]:
    """Yield SSE-payload dicts from a single graph run.

    Final two events are always ``{"kind": "result", "result": ...}``
    followed by ``{"kind": "done"}``. On exception, yields
    ``{"kind": "error", "message": ...}`` then ``done`` and re-raises.
    """
    running_count: dict[str, int] = defaultdict(int)
    step_started_at: dict[str, int] = {}
    step_emitted_running: set[str] = set()
    cumulative_cost: Decimal = Decimal("0")
    final_result: Any = None

    try:
        async for ev in graph.astream_events(initial_state, config, version="v2"):
            kind = ev.get("event", "")
            node = ev.get("name", "")

            if kind == "on_chain_start":
                if node in KNOWN_STEPS:
                    running_count[node] += 1
                    if node not in step_emitted_running:
                        step_emitted_running.add(node)
                        step_started_at[node] = _ts_ms()
                        yield {
                            "kind": "step",
                            "step_id": node,
                            "state": "running",
                            "progress": 0.0,
                            "elapsed_ms": 0,
                            "fanout": 1,
                        }
                elif node in SIDE_STEPS:
                    yield {
                        "kind": "step",
                        "step_id": node,
                        "state": "running",
                        "progress": 0.0,
                        "elapsed_ms": 0,
                        "side": True,
                    }
            elif kind == "on_chain_end":
                if node in KNOWN_STEPS:
                    if running_count[node] > 0:
                        running_count[node] -= 1
                    if running_count[node] == 0 and node in step_emitted_running:
                        yield {
                            "kind": "step",
                            "step_id": node,
                            "state": "done",
                            "progress": 1.0,
                            "elapsed_ms": _ts_ms() - step_started_at.get(node, _ts_ms()),
                        }
                        if node == "reconcile":
                            for pr in _period_states_from_reconcile(ev):
                                yield pr
                        elif node == "verifier":
                            for pr in _period_states_from_verifier(ev):
                                yield pr
                elif node in SIDE_STEPS:
                    yield {
                        "kind": "step",
                        "step_id": node,
                        "state": "done",
                        "progress": 1.0,
                        "elapsed_ms": 0,
                        "side": True,
                    }
                    if node == "finalize":
                        final_result = _final_from_event(ev) or final_result
            elif kind == "on_chat_model_end":
                model, usage = _model_and_usage(ev)
                if usage:
                    cumulative_cost += call_cost(model, usage)
                    yield {
                        "kind": "cost",
                        "cumulative_cost_usd": str(cumulative_cost.quantize(Decimal("0.0001"))),
                    }
    except Exception as exc:
        yield {"kind": "error", "message": str(exc)}
        yield {"kind": "done"}
        raise

    yield {"kind": "result", "result": _serialize_final(final_result)}
    yield {"kind": "done"}

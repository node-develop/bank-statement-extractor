"""SSE event generator over a single ``graph.astream_events`` invocation.

Pure async generator: no FastAPI, no HTTP. The router in
`src/api/routers/extract_stream.py` wraps these dicts into
``data: {json}\\n\\n`` lines.

Cost attribution is by **model name** (from each AIMessage's
``response_metadata.model_name``), not by graph-node name — LangGraph 1.x
does not auto-inject a ``langgraph:node=<name>`` tag.

Server-side fan-out aggregation collapses ``Send``-fanned branches of
a step (e.g. 10 parallel ``extract_account`` invocations) into one
``state:"running"`` + one ``state:"done"`` event per lane.
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
    # Collect errors[] reducer deltas across nodes so we can surface a
    # specific failure reason when the graph terminates without a final
    # (e.g. split_periods returning 0 chunks when ocr_text is empty).
    collected_errors: list[str] = []

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
                        # Reset gate so a subsequent critic-retry of the same
                        # node emits a fresh running event (the timeline lane
                        # otherwise stays "done" through the retry pass).
                        step_emitted_running.discard(node)
                        step_started_at.pop(node, None)
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
                    # When the critic dispatches a retry, the downstream
                    # KNOWN_STEPS that already completed (verifier, reconcile)
                    # are about to run again. Without this reset, the UI keeps
                    # showing them as "done" from the previous iteration while
                    # the retry's extract_* is still running — leaving the
                    # user with a paradoxical "verifier done, transactions
                    # still running" timeline. Emit idle events so the
                    # downstream lanes go back to pending; they'll re-emit
                    # "running" naturally on their next on_chain_start.
                    if node == "apply_critic_hint":
                        for downstream in ("verifier", "reconcile"):
                            step_emitted_running.discard(downstream)
                            step_started_at.pop(downstream, None)
                            yield {
                                "kind": "step",
                                "step_id": downstream,
                                "state": "idle",
                                "progress": 0.0,
                                "elapsed_ms": 0,
                            }
            elif kind == "on_chat_model_end":
                model, usage = _model_and_usage(ev)
                if usage:
                    cumulative_cost += call_cost(model, usage)
                    yield {
                        "kind": "cost",
                        "cumulative_cost_usd": str(cumulative_cost.quantize(Decimal("0.0001"))),
                    }

            # Harvest any `errors` reducer deltas the node emitted.
            if kind == "on_chain_end":
                out = (ev.get("data") or {}).get("output")
                if isinstance(out, dict):
                    errs = out.get("errors")
                    if isinstance(errs, list):
                        collected_errors.extend(str(e) for e in errs)
    except Exception as exc:
        yield {"kind": "error", "message": str(exc)}
        yield {"kind": "done"}
        raise

    if final_result is not None:
        yield {"kind": "result", "result": _serialize_final(final_result)}
        yield {"kind": "done"}
        return

    # `final` never arrived. Two valid sub-cases:
    #   (1) The graph paused at await_review (HITL) — `aget_state` returns a
    #       StateSnapshot whose `.interrupts` tuple is non-empty. NOTE: this
    #       diverges from `await graph.ainvoke(...)` which surfaces an
    #       `__interrupt__` key inside the returned state dict (see
    #       extract.py:237). The StateSnapshot exposes `.values` (state dict
    #       WITHOUT `__interrupt__`) and `.interrupts` (the tuple) as
    #       separate attributes. Mirror the sync endpoint's behaviour by
    #       reading from those two surfaces.
    #   (2) Genuine failure — split_periods produced 0 chunks, the fan-out
    #       dispatched 0 Send objects, finalize never ran. Surface a
    #       specific error so the frontend's catch sees it.
    snapshot = await graph.aget_state(config)
    state_values: dict[str, Any] = snapshot.values if hasattr(snapshot, "values") else {}
    snapshot_interrupts: Any = getattr(snapshot, "interrupts", ()) or ()

    if "final" not in state_values and snapshot_interrupts:
        # Local imports avoid a circular dep at module load and match the
        # pattern in extract.py.
        from uuid import uuid4

        from src.api import reviews as reviews_db
        from src.api.routers.extract import _build_partial_periods_on_pause
        from src.models import ExtractResult, PendingReview

        # snapshot_interrupts is a tuple of Interrupt(value=..., id=...).
        payload: dict[str, Any] = (
            snapshot_interrupts[0].value
            if snapshot_interrupts and hasattr(snapshot_interrupts[0], "value")
            else {}
        )
        suspect_count = len(payload.get("suspects", []))
        reason = payload.get("reason", "suspects_exceeded")
        extraction_id = str(uuid4())

        raw_obj = state_values.get("raw")
        statement_sha256 = getattr(raw_obj, "sha256", "") if raw_obj is not None else ""
        thread_id = (config.get("configurable") or {}).get("thread_id", "")

        reviews_db.insert_pending(
            extraction_id=extraction_id,
            thread_id=thread_id,
            statement_sha256=statement_sha256,
            suspect_count=suspect_count,
            reason=reason,
            review_payload=payload,
        )

        raw_errors = state_values.get("errors", []) or []
        errors_list: list[str] = list(raw_errors) if isinstance(raw_errors, list) else []
        raw_notes = state_values.get("notes", []) or []
        notes_list: list[str] = list(raw_notes) if isinstance(raw_notes, list) else []
        partial_periods = _build_partial_periods_on_pause(state_values)

        partial_result = ExtractResult(
            periods=partial_periods,
            statement_sha256=statement_sha256,
            errors=errors_list,
            notes=notes_list,
            pending_review=PendingReview(
                extraction_id=extraction_id,
                reason=reason,
                suspect_count=suspect_count,
            ),
        )
        yield {"kind": "result", "result": _serialize_final(partial_result)}
        yield {"kind": "done"}
        return

    # Genuine failure path.
    dedup = list(dict.fromkeys(collected_errors))
    if dedup:
        msg = "; ".join(dedup)
    else:
        msg = (
            "Graph completed without a final ExtractResult. "
            "Most likely cause: no period chunks detected."
        )
    yield {"kind": "error", "message": msg}
    yield {"kind": "done"}

"""Contract tests for the single-pass SSE generator and POST /extract/stream.

Tests use a fake graph whose `astream_events` returns a scripted list of
event dicts, so we exercise the aggregation/encoding logic without
touching Anthropic.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from src.api.streaming import stream_graph_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeMessage:
    """Stand-in for a langchain AIMessage with usage_metadata + response_metadata."""

    def __init__(self, model: str, usage: dict[str, int]) -> None:
        self.usage_metadata = usage
        self.response_metadata = {"model_name": model}


class FakeGraph:
    """Replays a scripted list of astream_events dicts."""

    def __init__(self, events: list[dict[str, Any]], final: Any | None = None) -> None:
        self._events = events
        self._final = final

    async def astream_events(
        self, state: dict[str, Any], config: dict[str, Any], version: str = "v2"
    ) -> AsyncIterator[dict[str, Any]]:
        for ev in self._events:
            await asyncio.sleep(0)
            yield ev
        # If a `finalize` end event wasn't scripted but a `final` value was provided,
        # synthesise one so the generator can pull the result.
        if self._final is not None and not any(
            e.get("event") == "on_chain_end" and e.get("name") == "finalize" for e in self._events
        ):
            yield {
                "event": "on_chain_end",
                "name": "finalize",
                "data": {"output": {"final": self._final}},
                "tags": [],
            }


def _step_start(name: str) -> dict[str, Any]:
    return {"event": "on_chain_start", "name": name, "data": {"input": {}}, "tags": []}


def _step_end(name: str, output: Any | None = None) -> dict[str, Any]:
    return {
        "event": "on_chain_end",
        "name": name,
        "data": {"output": output if output is not None else {}},
        "tags": [],
    }


def _model_end(usage: dict[str, int], model: str = "claude-sonnet-4-6") -> dict[str, Any]:
    return {
        "event": "on_chat_model_end",
        "name": "ChatAnthropic",
        "data": {"output": FakeMessage(model, usage)},
        "tags": [],
    }


@pytest.mark.asyncio
async def test_clean_run_emits_8_steps_in_order() -> None:
    """A clean Ixonia-like run emits 8 step running + 8 step done in order, then result + done."""
    happy_path = [
        "ingest",
        "split_periods",
        "classify_layout",
        "extract_account",
        "extract_summary",
        "extract_transactions",
        "verifier",
        "reconcile",
    ]
    events: list[dict[str, Any]] = []
    for n in happy_path:
        events.append(_step_start(n))
        events.append(_step_end(n))
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "deadbeef", "errors": []})

    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t1"}})]

    # Filter out side-graph step events (finalize is in SIDE_STEPS and gets
    # synthesised by FakeGraph so the result envelope can be assembled).
    step_events = [e for e in out if e["kind"] == "step" and not e.get("side")]
    assert len(step_events) == 16
    assert [e["step_id"] for e in step_events] == [n for n in happy_path for _ in (0, 1)]
    assert [e["state"] for e in step_events] == ["running", "done"] * 8
    kinds = [e["kind"] for e in out]
    assert kinds[-2:] == ["result", "done"]


@pytest.mark.asyncio
async def test_fanout_aggregates_to_single_lane_transition() -> None:
    """10 parallel Send branches of extract_account emit one running + one done."""
    events: list[dict[str, Any]] = []
    for _ in range(10):
        events.append(_step_start("extract_account"))
    for _ in range(10):
        events.append(_step_end("extract_account"))
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "x", "errors": []})

    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t2"}})]
    step_running = [
        e for e in out if e["kind"] == "step" and e["state"] == "running" and not e.get("side")
    ]
    step_done = [
        e for e in out if e["kind"] == "step" and e["state"] == "done" and not e.get("side")
    ]
    assert len(step_running) == 1, "exactly one running emission for the lane"
    assert len(step_done) == 1, "exactly one done emission for the lane"
    assert step_done[0]["step_id"] == "extract_account"


@pytest.mark.asyncio
async def test_cost_accumulates_as_decimal_string() -> None:
    """on_chat_model_end events sum into a monotonic 4dp decimal string."""
    events = [
        _step_start("extract_account"),
        _model_end({"input_tokens": 1000, "output_tokens": 200}, model="claude-sonnet-4-6"),
        _model_end({"input_tokens": 500, "output_tokens": 100}, model="claude-sonnet-4-6"),
        _step_end("extract_account"),
    ]
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "x", "errors": []})

    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t3"}})]
    costs = [e for e in out if e["kind"] == "cost"]
    assert len(costs) == 2
    assert all(isinstance(c["cumulative_cost_usd"], str) for c in costs)
    assert Decimal(costs[1]["cumulative_cost_usd"]) >= Decimal(costs[0]["cumulative_cost_usd"])
    # claude-sonnet-4-6 priced at $3/M input, $15/M output → expect non-zero cost
    assert Decimal(costs[0]["cumulative_cost_usd"]) > Decimal("0")


@pytest.mark.asyncio
async def test_terminates_with_result_then_done() -> None:
    """Final two events are exactly result + done."""
    graph = FakeGraph([], final={"periods": [], "statement_sha256": "x", "errors": []})
    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t4"}})]
    assert out[-2]["kind"] == "result"
    assert out[-1] == {"kind": "done"}


@pytest.mark.asyncio
async def test_unknown_model_priced_as_zero() -> None:
    """Cost summing tolerates unknown model names (call_cost contract)."""
    events = [
        _step_start("extract_account"),
        _model_end({"input_tokens": 1000, "output_tokens": 200}, model="claude-future-model-99"),
        _step_end("extract_account"),
    ]
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "x", "errors": []})
    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t5"}})]
    costs = [e for e in out if e["kind"] == "cost"]
    assert len(costs) == 1
    # Unknown model → call_cost returns 0 → emit "0.0000"
    assert costs[0]["cumulative_cost_usd"] == "0.0000"

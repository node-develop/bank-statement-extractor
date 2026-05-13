# Agent prompt — Phase 4: Backend SSE streaming

You are the `fastapi-engineer` subagent (primary) with optional
collaboration from `langgraph-engineer` for the `astream_events`
mapping. This is Phase 4 of `PRD-redesign.md` §5.

## Read first

1. `PRD-redesign.md` §5 (this phase's full spec — including event
   payload shapes).
2. `src/graph/builder.py` — current graph construction.
3. `src/api/routers/extract.py` — current POST /extract handler.
4. `src/api/main.py` — FastAPI app + lifespan.
5. `src/api/pricing.py` — cost calculation table.
6. **Context7 / latest LangGraph docs** for `astream_events`
   (version "v2") — verify the event shapes shipped in the
   LangGraph version pinned in `pyproject.toml`.

## What you ship

```
src/api/streaming.py                # NEW — astream_events → our SSE payloads
src/api/routers/extract_stream.py   # NEW — SSE endpoint
src/api/routers/extract.py          # EDIT — set X-Thread-Id header on response
src/api/main.py                     # EDIT — register new router
tests/api/test_extract_stream.py    # NEW — coverage per §5.5
```

## Endpoint contract

```
GET /extract/stream/{thread_id}
  → 200, content-type: text/event-stream
  → events: "data: <json>\n\n"
  → terminates with "data: {\"kind\":\"done\"}\n\n"
```

Payload variants — these MUST match the
`ExtractionProgress`-aggregating client in
`frontend/src/api.ts`:

```jsonc
{"kind": "step", "step_id": "extract_account",
 "state": "running" | "done" | "error",
 "progress": 0.0, "elapsed_ms": 0, "fanout": 10}

{"kind": "cost", "cumulative_cost_usd": 0.1834}

{"kind": "period", "chunk_id": "period_03", "state": "running" | "success" | "danger"}

{"kind": "done"}
```

## Wiring sketch

```python
# src/api/streaming.py
from collections import defaultdict
from langchain_core.callbacks import AsyncCallbackHandler

async def stream_graph_events(graph, input_state, config):
    """Yield JSON-serialisable progress dicts."""
    cumulative_cost = Decimal("0")
    step_state = {}  # step_id -> running/done

    async for ev in graph.astream_events(input_state, config, version="v2"):
        name = ev["event"]
        node = ev.get("name") or ""
        if name == "on_chain_start" and node in KNOWN_STEPS:
            yield {"kind": "step", "step_id": node, "state": "running",
                   "progress": 0.0, "elapsed_ms": 0,
                   "fanout": _fanout_for(input_state, node)}
        elif name == "on_chain_end" and node in KNOWN_STEPS:
            yield {"kind": "step", "step_id": node, "state": "done",
                   "progress": 1.0, "elapsed_ms": _elapsed(ev)}
        elif name == "on_chat_model_end":
            cost = _cost_from_usage(ev["data"]["output"].usage_metadata, node)
            cumulative_cost += cost
            yield {"kind": "cost", "cumulative_cost_usd": float(cumulative_cost)}
        # also detect period_state transitions from reducer outputs
    yield {"kind": "done"}
```

Where `KNOWN_STEPS` is the same 8-step list as the frontend's
`AGENT_STEPS` array. The frontend's `AgentStepSpec.id` strings are
the source of truth; mirror them in Python as a constant.

## Acceptance criteria

- `curl -N http://localhost:8000/extract/stream/<tid>` against a
  running extract prints SSE events terminated by `{"kind":"done"}`.
- Final cost in stream === `result.ExtractResult` cost (within $0.001).
- All 8 step transitions emitted in order for a clean Ixonia run.
- Client-disconnect mid-stream does not leak coroutines or block the
  graph (test with `aiohttp` cancelling the request).
- `pytest tests/api/test_extract_stream.py -q` — 3 new tests pass:
  1. clean run streams the expected sequence
  2. unreconciled period emits `{"kind":"period","state":"danger"}`
  3. client disconnect cleanly cancels the generator

## Do NOT

- Do NOT change the LangGraph topology to surface progress. Use
  `astream_events`; the graph stays untouched.
- Do NOT swallow exceptions in the SSE generator — they must
  propagate as a final `{"kind":"error", "message": ...}` event,
  then the stream closes.
- Do NOT use the existing checkpointer database for progress
  storage. Progress is ephemeral — if the client reconnects after
  a drop, they re-poll `GET /extract/result/{thread_id}` (a
  separate endpoint to add only if needed).

## Report back

`done`, `verified`, `left_todo`, `files_touched`. Cite the
LangGraph version + `astream_events` doc you used.

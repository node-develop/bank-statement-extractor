# Frontend redesign — Bank Statement Extractor design system + live SSE timeline

- **Date:** 2026-05-13
- **Owner:** dev@artka.dev
- **Status:** Approved
- **Supersedes:** `handoff_package/PRD-redesign.md` v1.0 (kept as input artifact;
  this spec is the authoritative implementation contract).

## 1 · Goal

Replace the current minimal React frontend with the Bank Statement Extractor
design system (purple accent, Inter / JetBrains Mono, agent timeline, JSON
viewer, review modal), and wire a **single-pass** SSE pipeline so the agent
timeline animates in real time while the LangGraph extraction runs.

Success criteria:

1. End-to-end run of `Task/Binder2_Redacted.pdf` through the UI shows the agent
   timeline filling lane-by-lane in real time, 10 period chips light up, the
   results view renders all 10 reconciled periods.
2. `LangSmith` shows exactly **one** graph run per upload (no doubled cost).
3. `pytest -q` green, including 3 new SSE backend tests.
4. `ruff`, `mypy --strict src`, `biome check`, `tsc --noEmit` all clean.

## 2 · Why the handoff_package needs amendments

The `critic` subagent reviewed `handoff_package/` against the 12 rules in
`CLAUDE.md` and returned **rework** with four HIGH findings:

- **H1** — `agents/04-backend-streaming.md:60` describes SSE as a *second*
  `graph.astream_events()` invocation parallel to the existing
  `graph.ainvoke()` call in `POST /extract`. That is two full extractions per
  upload — ×2 Anthropic spend, ×2 latency. Violates rules 4 + 6.
- **H2** — In LangGraph 1.x, `on_chain_start` events fire once per `Send`
  fan-out branch. The handoff's wiring emits a `kind:"step", state:"running"`
  per fire, so `extract_account` on Ixonia (10 periods) would spam the same
  timeline lane 10 times and the first `on_chain_end` would mark the step
  done while 9 branches are still running.
- **H3** — `src/api/main.py:121-123` CORS config does not expose
  `X-Thread-Id` (`expose_headers` missing), so the planned client header
  read returns `null` cross-origin.
- **H4** — `handoff_package/frontend/src/lib/agentSteps.ts:34` and
  `components/ResultsView.tsx:27-28` call `parseFloat` on Decimal money
  strings, violating the precision contract documented in
  `frontend/src/types.ts` and PRD §1.3.

Plus four MED / three LOW findings (see §10).

## 3 · Architectural decision — single-pass SSE

We add a new endpoint `POST /extract/stream` that accepts the same multipart
form as `POST /extract` and returns `text/event-stream`. The handler runs
`graph.astream_events(..., version="v2")` exactly once, emits typed progress
events as the graph runs, and ends with a `kind:"result"` event carrying the
final `ExtractResult` followed by `kind:"done"`.

The existing `POST /extract` is **unchanged** — it still returns
`application/json` and is consumed by:
- `tests/api/test_extract.py`, `tests/api/test_reviews.py`
- `tests/fixtures/run_all.py` (held-out fixture runner)
- The current `frontend/src/api.ts` (kept as a fallback path).

H3 disappears entirely under this approach because there is no
`X-Thread-Id` to expose; the stream is the response.

Rejected alternatives:

- **Background task + per-thread `asyncio.Queue`** — closer to handoff
  intent but adds a per-process registry, garbage-collection of stale
  queues, a race condition when the GET arrives after events start
  flowing, and still requires the H3 CORS fix.
- **Drop P4 entirely; animate timeline on a static timer** — honest
  fallback if backend work is deprioritised, but the README itself says
  this "loses the entire 'watch agents work' value prop." Not chosen.

## 4 · Backend contract — `POST /extract/stream`

### 4.1 Request

```
POST /extract/stream
Content-Type: multipart/form-data
form fields:
  file       application/pdf  required ≤ 80 MB
  ocr_text   text/plain       optional ≤  5 MB
```

Validation rules and size limits are identical to `POST /extract`
(`src/api/routers/extract.py`). Any 4xx is returned **before** the stream
opens so the client gets a normal JSON error.

### 4.2 Response

`text/event-stream`, events terminated by `\n\n`. Payload variants:

```jsonc
{"kind": "step", "step_id": "extract_account",
 "state": "running" | "done" | "error",
 "progress": 0.0, "elapsed_ms": 1234, "fanout": 7}

{"kind": "cost", "cumulative_cost_usd": "0.1834"}    // decimal string, 4 dp

{"kind": "period", "chunk_id": "period_03",
 "state": "running" | "success" | "danger"}

{"kind": "result", "result": <ExtractResult>}        // exactly one, near end

{"kind": "done"}                                     // always the last event

{"kind": "error", "message": "..."}                  // terminal on failure
```

`cumulative_cost_usd` is a string so the precision contract holds end-to-end
(money values never become floats). The frontend formats this with the same
`fmt$` helper used for everything else.

### 4.3 Fan-out aggregation (resolves H2)

The known fan-out steps are `classify_layout`, `extract_account`,
`extract_summary`, `extract_transactions`. They emit one
`on_chain_start` / `on_chain_end` per `Send` branch. The streamer
maintains:

```python
running_count: dict[str, int] = defaultdict(int)
step_started: set[str] = set()
```

Behaviour:

- On the **first** `on_chain_start` for a step_id → emit
  `state:"running"` once. Subsequent starts only update the
  `fanout` field but do not re-emit `running`.
- On every `on_chain_end` → `running_count[step] -= 1`. Only when
  `running_count[step] == 0` do we emit `state:"done"`.
- Side-graph nodes (`merge_state`, `critic`, `apply_critic_hint`,
  `await_review`, `finalize`) are recognised but emitted as a
  separate `{"kind":"step","step_id":"<name>","state":"running",
  "side":true}` envelope so the frontend can render them as a small
  neutral indicator (resolves L1) rather than ignoring them.

### 4.4 Per-period state

Verifier and reconcile node outputs are folded into per-chunk state
transitions:

- `verifier_reports[].confidence < threshold` OR `suspects.length > 0`
  → emit `{"kind":"period","chunk_id":...,"state":"danger"}`.
- `reconciliations[].reconciled == true` → `state:"success"`.
- Default while the chunk is mid-run → `state:"running"`.

### 4.5 Cost calculation

`on_chat_model_end` carries `usage_metadata`. We sum it against the
existing `src/api/pricing.py` table (rule 5 — do not duplicate the
table; import it). After each model end, emit `kind:"cost"` with the
new cumulative total. The final `ExtractResult.cumulative_cost_usd`
field (if present) is the same Decimal as the last cost event ± rounding.

### 4.6 Cancellation

The handler wraps `async for ev in graph.astream_events(...)` in
`try / except asyncio.CancelledError` so a client disconnect cleanly
unwinds the graph and the temp file is deleted in `finally`. There is
no zombie generator and no half-written checkpoint.

### 4.7 Files

- `src/api/streaming.py` — pure helper: `stream_graph_events(graph,
  state, config) -> AsyncIterator[dict]`. No FastAPI imports.
- `src/api/routers/extract_stream.py` — FastAPI router with
  `POST /extract/stream`. Handles multipart, validation, temp-file
  lifecycle, and serialises dicts from `streaming.stream_graph_events`
  into `data: <json>\n\n` lines.
- `src/api/main.py` — register the new router. CORS is unchanged.

## 5 · Frontend amendments to the handoff drop

| # | Drop file | Fix |
|---|-----------|-----|
| F1 | `lib/agentSteps.ts` | Replace `parseFloat` in `fmt$()` with BigInt-cents string parsing. New helper `centsFromDecimalString("597068.70") -> 59706870n`, format with regex-based thousand separators. (resolves H4) |
| F2 | `components/ResultsView.tsx` | Delete the cross-period `aggregate()` helper and the hero stats block it feeds. Per-period numbers in `PeriodCard` are sufficient and avoid any floating-point aggregation. (resolves H4 in `ResultsView`) |
| F3 | `styles/tokens.css` | Remove the `@import url("…fonts.googleapis.com…")` line. Only the `<link>` tags injected into `index.html` per `agents/01-foundation.md` step 2 remain. (resolves M4) |
| F4 | `components/ReviewModal.tsx` | Replace the hard-coded `"Too many verifier suspects"` label with `REASON_LABEL[period.pending_review?.reason]` where the map covers all three values from `PendingReview.reason`. (resolves L3) |
| F5 | `lib/agentSteps.ts`, `components/ProcessingView.tsx` | Add inline comment that `AGENT_STEPS` is the happy-path 8-lane list. `ProcessingView` shows a small secondary indicator ("Reviewing", "Retrying", "Awaiting human review") sourced from `side`-flagged step events when the active node is not in `AGENT_STEPS`. (resolves L1) |
| F6 | `frontend/src/api.ts` | Add `extractStatementStreaming(pdf, ocr?, onProgress?)`. Implementation: `fetch("/extract/stream", { method: "POST", body, signal })`, read `response.body` via a `ReadableStream` reader, split on `\n\n`, parse `data: …` lines, feed `kind:"step"/"cost"/"period"` into an accumulator passed to `onProgress`. On `kind:"result"` resolve with `ExtractResult`; on `kind:"error"` throw `ApiError`. The original JSON-based `extractStatement` stays for fallback and test code. |

`App.tsx` uses `extractStatementStreaming` instead of `extractStatement`. If
the new endpoint returns 404 (deploy lag) the catch-block logs a warning
and falls back to `extractStatement` (graceful degradation; rule 12 — the
fallback path is loud in the console, not silent in the UI).

`frontend/src/types.ts` is **not** modified — it already exports everything
the dropped components import. `types-progress.ts` stays as a separate file
so the JSON-only path is unaffected.

## 6 · Test minimum

We accept the PRD's stance that full frontend unit-test coverage is out of
scope. We require, additionally:

1. `tests/api/test_extract_stream.py` — three tests:
   - **clean run**: mock `graph.astream_events` with a synthetic event
     trace that mirrors a clean Ixonia run; assert the SSE bytes
     decode into a list whose first 16 entries are exactly the 8
     `kind:"step" running` and 8 `kind:"step" done` transitions in
     graph order, plus exactly one `kind:"result"` and one
     `kind:"done"`.
   - **suspect period**: mock a verifier event that flags suspects;
     assert a `{"kind":"period", "state":"danger"}` is emitted for the
     affected `chunk_id`.
   - **client disconnect**: use `httpx.AsyncClient` with a cancelled
     task; assert no `RuntimeWarning: coroutine was never awaited`
     and the temp file is removed from `/tmp`.

2. `src/api/streaming.py` is a pure async generator that takes a
   pre-built graph and an event stream — easy to unit-test without
   spinning up FastAPI.

3. Frontend: one type guard `parseSseEvent(line: string):
   ProgressEvent | null` rejects unknown `kind` values with a console
   warning; that's the boundary check on the SSE contract. No RTL /
   vitest setup is added in this spec (out of scope; tracked as
   follow-up).

## 7 · Phased plan

| # | Phase | Owner | Budget | Gate |
|---|-------|-------|--------|------|
| 0 | Pin LangGraph contract (`mcp__context7__query-docs` for `langgraph astream_events v2` against `langgraph>=1.0.8`; record event-field layout in `docs/architecture.md`) | langgraph-engineer | 1h | docs commit only |
| 1 | Foundation (CSS / fonts / SVG, per `agents/01-foundation.md`) + **F3** | react-engineer | 1h | `pnpm dev` runs; `--accent == #5B33F0` |
| 2 | Primitives + types (`agents/02-primitives.md`) + **F1** | react-engineer | 1.5h | `tsc --noEmit`, `biome check` clean |
| 3 | Stateless components (`agents/03-stateless.md`) + **F2**, **F4**, **F5** | react-engineer | 3h | `tsc`, `biome`, smoke render with fixture |
| 4 | Backend SSE (`src/api/streaming.py`, `src/api/routers/extract_stream.py`, `main.py` register) + 3 tests | fastapi-engineer + langgraph-engineer | 3.5h | `pytest tests/api/test_extract_stream.py -q` green; live `curl -N` prints sequence + `kind:"done"` |
| 5 | Frontend state machine (`agents/05-state-machine-and-sse.md` Phase 5 portion) + side-step indicator | react-engineer | 2h | `tsc`, `biome`; upload→processing(inert)→results round-trip |
| 6 | SSE client wiring (**F6**: `extractStatementStreaming` + ReadableStream parser + AbortController + 404-fallback) | react-engineer | 1.5h | E2E smoke: Ixonia run lights up timeline; Cancel closes stream in Network tab |
| 7 | Critic final pass + cleanup (`UploadForm.tsx`, `ReconciliationBanner.tsx` deleted) | critic | 0.5h | critic verdict `approve` |

**Total: ~14h.**

Phases 1→2→3→5→6 are sequential (each consumes the previous phase's
files). Phase 4 (backend) runs **in parallel** with Phases 1-3 and 5 if
agent capacity allows. Phase 6 blocks on both Phase 4 (endpoint live)
and Phase 5 (App.tsx replaced).

## 8 · Files touched

```
docs/architecture.md                                       EDIT (Phase 0: pin astream_events fields)
docs/superpowers/specs/2026-05-13-frontend-redesign-design.md  NEW (this file)
src/api/streaming.py                                       NEW (Phase 4)
src/api/routers/extract_stream.py                          NEW (Phase 4)
src/api/main.py                                            EDIT (Phase 4: register router)
tests/api/test_extract_stream.py                           NEW (Phase 4)

frontend/index.html                                        EDIT (Phase 1)
frontend/src/main.tsx                                      EDIT (Phase 1)
frontend/src/index.css                                     EDIT (Phase 1)
frontend/public/{logo,mark,wordmark-short}.svg             NEW  (Phase 1)
frontend/src/styles/{tokens,components}.css                NEW  (Phase 1; tokens.css with F3 applied)
frontend/src/types-progress.ts                             NEW  (Phase 2)
frontend/src/lib/agentSteps.ts                             NEW  (Phase 2; F1 applied)
frontend/src/components/icons/index.tsx                    NEW  (Phase 2)
frontend/src/components/ui/{Button,Chip,SectionLabel}.tsx  NEW  (Phase 2)
frontend/src/components/Header.tsx                         NEW  (Phase 3)
frontend/src/components/UploadView.tsx                     NEW  (Phase 3)
frontend/src/components/AgentTimeline.tsx                  NEW  (Phase 3)
frontend/src/components/PeriodChipsBar.tsx                 NEW  (Phase 3)
frontend/src/components/TransactionsTable.tsx              NEW  (Phase 3)
frontend/src/components/PeriodCard.tsx                     REPLACE (Phase 3)
frontend/src/components/JSONViewer.tsx                     NEW  (Phase 3)
frontend/src/components/ReconciliationBanner.tsx           DELETE (Phase 7)
frontend/src/components/ResultsView.tsx                    NEW  (Phase 3; F2 applied)
frontend/src/components/ProcessingView.tsx                 NEW  (Phase 5; F5 indicator)
frontend/src/components/ReviewModal.tsx                    REPLACE (Phase 5; F4 applied)
frontend/src/components/UploadForm.tsx                     DELETE (Phase 7)
frontend/src/App.tsx                                       REPLACE (Phase 5)
frontend/src/api.ts                                        EDIT (Phase 6: F6 — new streaming function + parser + AbortController)
```

## 9 · Out of scope (explicit)

- Self-hosting Inter / JetBrains Mono woff2 (strict CSP environments).
  Separate PR if needed.
- LocalStorage persistence of review-modal field edits.
- "Compare to etalon" toggle on the results view.
- Keyboard-driven step-through of suspects.
- `lucide-react` or any icon library. Icons stay inline SVG.
- Global state library. Local `useState` in `App.tsx` is sufficient.
- Polling fallback for SSE failure. Per skill rule, no polling.
- Frontend unit-test framework (vitest + RTL). Tracked as a follow-up.

## 10 · Critic findings — disposition

| ID | Severity | Status |
|----|----------|--------|
| H1 — dual graph invocation                     | HIGH | Resolved by §3 (single endpoint). |
| H2 — fan-out spam in `on_chain_start`          | HIGH | Resolved by §4.3 (server-side aggregation). |
| H3 — CORS `expose_headers` missing             | HIGH | Obsolete — no header used. |
| H4 — `parseFloat` on money strings             | HIGH | Resolved by F1 (BigInt-cents) and F2 (aggregate removed). |
| M1 — no frontend tests                         | MED  | Mitigated by §6: backend contract test + frontend type guard. Full RTL setup deferred. |
| M2 — LangGraph version not pinned              | MED  | Resolved by Phase 0 (context7 + docs commit). |
| M3 — README vs PRD §9 contradiction            | MED  | Resolved — this spec is authoritative; P4 is required. |
| M4 — Google Fonts double-import                | MED  | Resolved by F3. |
| L1 — `AGENT_STEPS` happy-path only             | LOW  | Resolved by F5 (side-step indicator). |
| L2 — P6 has no backend liveness gate           | LOW  | Resolved — Phase 6 gate is the live E2E smoke. |
| L3 — `ReviewModal` reason label hard-coded     | LOW  | Resolved by F4. |

## 11 · Risk register

| Risk | Mitigation |
|------|------------|
| `astream_events` event shape changes between LangGraph minor versions | Phase 0 pins the contract in `docs/architecture.md` for the pinned version range. CI does not yet alert on a bump; manual re-check on every `langgraph` upgrade. |
| Server-side fan-out aggregation drifts from actual graph topology | The `KNOWN_STEPS` list and `running_count` logic live next to a single test (`test_extract_stream.py::test_fanout_aggregation`) that mocks 10-period fan-out and asserts a single `state:"done"`. |
| Browser quirk in `ReadableStream` SSE parser | Tested manually in Chromium + Safari + Firefox during Phase 6 smoke. If Safari misbehaves, fall back to a SSE polyfill but **not** to polling. |
| `fmt$` BigInt parsing rejects an unexpected string shape | The parser throws on malformed input; UI renders `—` (existing convention). Logged to console with the offending string. |
| The held-out fixture runner (`tests/fixtures/run_all.py`) breaks because of an unrelated change | Out of scope here — runner uses the JSON `POST /extract` which is untouched. |

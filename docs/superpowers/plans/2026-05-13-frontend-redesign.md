# Frontend redesign + live SSE timeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Bank Statement Extractor design system onto `frontend/` and stream live LangGraph progress to it via a new single-pass SSE endpoint.

**Architecture:** New `POST /extract/stream` returns `text/event-stream`; one `graph.astream_events(version="v2")` invocation feeds typed `step` / `cost` / `period` events with server-side fan-out aggregation, ends with `kind:"result"` (full `ExtractResult`) + `kind:"done"`. Existing `POST /extract` (JSON) untouched. Frontend swaps to a state machine (upload → processing → results) consuming SSE via fetch + ReadableStream parser.

**Tech Stack:** FastAPI, LangGraph 1.0.8+, LangChain Anthropic, React 19 + Vite + TS, Biome, vendored CSS tokens + components.

**Source spec:** `docs/superpowers/specs/2026-05-13-frontend-redesign-design.md`

**Source drop (vendored, do not edit in place):** `handoff_package/frontend/`

---

## File map

### Backend (new / edited)
- `docs/architecture.md` — append a short "SSE event mapping (Phase 0)" section
- `src/api/streaming.py` — NEW; pure `AsyncIterator[dict]` over `graph.astream_events`
- `src/api/routers/extract_stream.py` — NEW; FastAPI `POST /extract/stream`
- `src/api/main.py` — EDIT (one line: register `extract_stream_router`)
- `tests/api/test_extract_stream.py` — NEW; 3 contract tests

### Frontend (new / edited / deleted)
- `frontend/index.html` — EDIT (Google Fonts `<link>` in `<head>`)
- `frontend/src/main.tsx` — EDIT (CSS import order)
- `frontend/src/index.css` — EDIT (gut to one-line comment)
- `frontend/public/{logo,mark,wordmark-short}.svg` — NEW (copied)
- `frontend/src/styles/tokens.css` — NEW (copied, with `@import` line stripped — F3)
- `frontend/src/styles/components.css` — NEW (copied verbatim)
- `frontend/src/types-progress.ts` — NEW (copied, `cumulative_cost_usd: string`)
- `frontend/src/lib/agentSteps.ts` — NEW (BigInt-cents `fmt$` — F1)
- `frontend/src/components/icons/index.tsx` — NEW (copied)
- `frontend/src/components/ui/{Button,Chip,SectionLabel}.tsx` — NEW (copied)
- `frontend/src/components/Header.tsx` — NEW (copied)
- `frontend/src/components/UploadView.tsx` — NEW (copied)
- `frontend/src/components/AgentTimeline.tsx` — NEW (copied)
- `frontend/src/components/PeriodChipsBar.tsx` — NEW (copied)
- `frontend/src/components/TransactionsTable.tsx` — NEW (copied)
- `frontend/src/components/PeriodCard.tsx` — REPLACE (drop)
- `frontend/src/components/JSONViewer.tsx` — NEW (copied)
- `frontend/src/components/ResultsView.tsx` — NEW (copied with F2: `aggregate()` deleted + hero stats simplified)
- `frontend/src/components/ProcessingView.tsx` — NEW (copied with side-step indicator — F5 — and string-cost display)
- `frontend/src/components/ReviewModal.tsx` — REPLACE (drop with F4: `REASON_LABEL[reason]`)
- `frontend/src/api.ts` — EDIT (add `extractStatementStreaming` — F6)
- `frontend/src/App.tsx` — REPLACE (drop, wired to streaming)
- `frontend/src/components/UploadForm.tsx` — DELETE (Phase 7)
- `frontend/src/components/ReconciliationBanner.tsx` — DELETE (Phase 7)

---

## Phase 0 — Pin LangGraph event contract

### Task 0.1: Verify `astream_events` v2 fields against pinned LangGraph

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Pull current docs**

Run:
```bash
# In Claude Code session — uses mcp-context7
# Resolve library id, then query specifically for astream_events v2 event field layout
```
Use `mcp__context7__resolve-library-id` with `query="langgraph"` then `mcp__context7__query-docs` with `library_id=<resolved>`, `query="astream_events version v2 on_chain_start on_chat_model_end usage_metadata"`.

- [ ] **Step 2: Append "SSE event mapping" section to `docs/architecture.md`**

Append at the end of the file:

```markdown
## SSE event mapping (Phase 0, langgraph >= 1.0.8)

`graph.astream_events(state, config, version="v2")` yields dicts with:

| Field | Type | Meaning |
|---|---|---|
| `event` | `"on_chain_start" \| "on_chain_end" \| "on_chat_model_end" \| ...` | event kind |
| `name` | `str` | node id (matches `add_node("name", ...)`) |
| `run_id` | `str` (UUID) | unique per invocation, not per `Send` branch |
| `tags` | `list[str]` | propagated from `config.tags` |
| `data.input` | `dict` | node input on `_start` |
| `data.output` | `Any` | node output on `_end` |
| `data.output.usage_metadata` | `dict[str, int]` | on `on_chat_model_end` only |

Fan-out: each `Send(...)` branch fires its own `on_chain_start` /
`on_chain_end` pair under the same `name`. Server-side aggregation
(see `src/api/streaming.py`) merges N branches into one timeline lane
per step.
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git -c commit.gpgsign=false commit -m "docs(arch): pin langgraph astream_events v2 contract"
```

---

## Phase 1 — Foundation (CSS / fonts / SVG)

### Task 1.1: Vendor the design-system static files

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/components.css`
- Create: `frontend/public/logo.svg`, `frontend/public/mark.svg`, `frontend/public/wordmark-short.svg`

- [ ] **Step 1: Copy three SVGs verbatim**

```bash
mkdir -p frontend/public frontend/src/styles
cp handoff_package/frontend/public/logo.svg          frontend/public/logo.svg
cp handoff_package/frontend/public/mark.svg          frontend/public/mark.svg
cp handoff_package/frontend/public/wordmark-short.svg frontend/public/wordmark-short.svg
```

- [ ] **Step 2: Copy `components.css` verbatim**

```bash
cp handoff_package/frontend/src/styles/components.css frontend/src/styles/components.css
```

- [ ] **Step 3: Copy `tokens.css` and strip the `@import` line (F3 fix)**

```bash
cp handoff_package/frontend/src/styles/tokens.css frontend/src/styles/tokens.css
```

Then edit `frontend/src/styles/tokens.css` and **delete line 9** (the `@import url("https://fonts.googleapis.com/...")` line). The block comment on lines 7-8 stays.

- [ ] **Step 4: Verify the delete**

Run: `grep "@import.*fonts.googleapis" frontend/src/styles/tokens.css`
Expected: no output (exit 1).

### Task 1.2: Wire CSS + Google Fonts into the app entry

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add Google Fonts `<link>` to `index.html`**

Inside `<head>`, after the existing `<meta>` and `<title>` tags, add:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap"
  rel="stylesheet"
/>
```

(Family list matches `tokens.css` block-comment expectations: Inter + JetBrains Mono + Newsreader.)

- [ ] **Step 2: Add CSS imports to `main.tsx`**

Edit `frontend/src/main.tsx`. Add these two lines **above** `import "./index.css";`:

```ts
import "./styles/tokens.css";
import "./styles/components.css";
```

- [ ] **Step 3: Gut `frontend/src/index.css`**

Replace the entire file contents with:

```css
/* Reserved. Token + component styles live in src/styles/. */
```

- [ ] **Step 4: Verify `pnpm dev` runs and `--accent` resolves**

Run: `cd frontend && pnpm dev`
Open `http://localhost:5173` in the browser. In DevTools console run:

```js
getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()
```

Expected: `"#5B33F0"`.

Also check `Network` tab: `fonts.googleapis.com/css2?family=Inter…` loads **once** (not twice).

- [ ] **Step 5: Commit**

```bash
git add frontend/public frontend/src/styles frontend/index.html frontend/src/main.tsx frontend/src/index.css
git -c commit.gpgsign=false commit -m "feat(frontend): vendor design-system tokens + components.css + svg

Drop tokens (purple accent #5B33F0, Inter/JetBrains Mono/Newsreader)
and component classes from handoff_package. Strip @import to avoid
loading Google Fonts twice — preconnect + <link> in index.html is the
single source."
```

---

## Phase 2 — Primitives (icons, UI, lib, types)

### Task 2.1: Copy types-progress + icons + ui primitives

**Files:**
- Create: `frontend/src/types-progress.ts`
- Create: `frontend/src/components/icons/index.tsx`
- Create: `frontend/src/components/ui/Button.tsx`
- Create: `frontend/src/components/ui/Chip.tsx`
- Create: `frontend/src/components/ui/SectionLabel.tsx`

- [ ] **Step 1: Copy files verbatim**

```bash
mkdir -p frontend/src/components/icons frontend/src/components/ui frontend/src/lib
cp handoff_package/frontend/src/types-progress.ts                    frontend/src/types-progress.ts
cp handoff_package/frontend/src/components/icons/index.tsx           frontend/src/components/icons/index.tsx
cp handoff_package/frontend/src/components/ui/Button.tsx             frontend/src/components/ui/Button.tsx
cp handoff_package/frontend/src/components/ui/Chip.tsx               frontend/src/components/ui/Chip.tsx
cp handoff_package/frontend/src/components/ui/SectionLabel.tsx       frontend/src/components/ui/SectionLabel.tsx
```

- [ ] **Step 2: Change `cumulative_cost_usd` to string in `types-progress.ts`**

Spec §4.2 specifies the SSE cost payload is a decimal string. Edit `frontend/src/types-progress.ts`. Change:

```ts
  /** Cumulative LLM spend, USD */
  cumulative_cost_usd: number;
```

to:

```ts
  /** Cumulative LLM spend, USD — decimal string with 4dp (precision contract) */
  cumulative_cost_usd: string;
```

- [ ] **Step 3: Run typecheck (will fail because `agentSteps.ts` doesn't exist yet — that's OK; we wire it in Task 2.2)**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: errors only about missing `./lib/agentSteps`. No errors in `types-progress.ts`, `icons/index.tsx`, or `ui/*.tsx`.

### Task 2.2: Write `lib/agentSteps.ts` with BigInt-cents `fmt$` (F1)

**Files:**
- Create: `frontend/src/lib/agentSteps.ts`

- [ ] **Step 1: Write the file**

Create `frontend/src/lib/agentSteps.ts` with this content (replaces the handoff version that used `parseFloat`):

```ts
/**
 * Static spec of the LangGraph node sequence + money formatting helpers.
 *
 * `AGENT_STEPS` is the **happy-path** 8-lane list shown in the live timeline.
 * Side-graph nodes — `merge_state`, `critic`, `apply_critic_hint`,
 * `await_review`, `finalize` — are NOT in this list. The processing view
 * shows them via a secondary "Side step" indicator driven off SSE events
 * tagged `side: true`.
 *
 * Money helpers use BigInt cents internally (no parseFloat) per the
 * precision contract in `src/types.ts`.
 */

export interface AgentStepSpec {
  id: string;
  name: string;
  /** CSS var ref, e.g. "var(--agent-ingest)" */
  color: string;
  /** Runs once per (period_chunk_id) Send fan-out */
  runs_per_period: boolean;
  /** Baseline duration in ms — used only as a fallback when no SSE */
  duration_ms: number;
  /** Copy shown in the active-step indicator */
  desc: string;
}

export const AGENT_STEPS: AgentStepSpec[] = [
  { id: "ingest",                name: "ingest",                color: "var(--agent-ingest)",       runs_per_period: false, duration_ms: 800,  desc: "Reading PDF…" },
  { id: "split_periods",         name: "split_periods",         color: "var(--agent-split)",        runs_per_period: false, duration_ms: 200,  desc: "Splitting into periods…" },
  { id: "classify_layout",       name: "classify_layout",       color: "var(--agent-layout)",       runs_per_period: true,  duration_ms: 1800, desc: "Classifying layout…" },
  { id: "extract_account",       name: "extract_account",       color: "var(--agent-account)",      runs_per_period: true,  duration_ms: 1900, desc: "Extracting account metadata…" },
  { id: "extract_summary",       name: "extract_summary",       color: "var(--agent-summary)",      runs_per_period: true,  duration_ms: 2100, desc: "Extracting period summaries…" },
  { id: "extract_transactions",  name: "extract_transactions",  color: "var(--agent-transactions)", runs_per_period: true,  duration_ms: 4600, desc: "Extracting transactions…" },
  { id: "verifier",              name: "verifier",              color: "var(--agent-verifier)",     runs_per_period: false, duration_ms: 400,  desc: "Verifying chunks…" },
  { id: "reconcile",             name: "reconcile",             color: "var(--agent-reconcile)",    runs_per_period: false, duration_ms: 300,  desc: "Reconciling totals…" },
];

/**
 * Parse a decimal money string ("597068.70" / "100.5" / "100" / "-12.34")
 * into BigInt cents (59706870n). Throws on malformed input.
 */
export function centsFromDecimalString(s: string): bigint {
  const m = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(s.trim());
  if (m === null) throw new Error(`fmt$: malformed money string "${s}"`);
  const sign = m[1];
  const whole = m[2];
  const frac = (m[3] ?? "") + "00";
  return BigInt(sign + whole + frac.slice(0, 2));
}

/** Format BigInt cents as "$1,234.56" (or "-$12.34"). */
export function formatCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const c = (abs % 100n).toString().padStart(2, "0");
  const wholeStr = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (negative ? "-$" : "$") + wholeStr + "." + c;
}

/** Display helper: Decimal string → "$1,234.56". Returns "—" on malformed input. */
export function fmt$(s: string | null | undefined): string {
  if (typeof s !== "string") return "—";
  try {
    return formatCents(centsFromDecimalString(s));
  } catch {
    return "—";
  }
}

/** Shortform for hero stats — "$1,234" (no cents). */
export function fmt$short(s: string | number): string {
  if (typeof s === "number") {
    return "$" + Math.round(s).toLocaleString("en-US");
  }
  try {
    const cents = centsFromDecimalString(s);
    const dollars = cents / 100n;
    return "$" + dollars.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  } catch {
    return "—";
  }
}

/** Format a period's `Apr 2025` from a YYYY-MM-DD string. */
export function formatMonth(iso: string): string {
  const [y, m] = iso.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[parseInt(m, 10)]} ${y}`;
}
```

- [ ] **Step 2: Manual smoke in the browser console (after Phase 1 dev server is running)**

In DevTools console after a `pnpm dev` reload:

```js
const { fmt$, fmt$short, centsFromDecimalString, formatCents } = await import("/src/lib/agentSteps.ts");
console.assert(fmt$("597068.70") === "$597,068.70", "Ixonia beginning balance");
console.assert(fmt$("100.5")     === "$100.50",     "single-digit fractional");
console.assert(fmt$("100")       === "$100.00",     "integer");
console.assert(fmt$("-12.34")    === "-$12.34",     "negative");
console.assert(fmt$("99999999999999.99") === "$99,999,999,999,999.99", "above 2^53");
console.assert(fmt$("not a num") === "—",           "garbage → dash");
console.log("fmt$ smoke OK");
```

Expected: no console.assert failures; final log line prints.

- [ ] **Step 3: Run `tsc --noEmit` and `biome check`**

Run: `cd frontend && pnpm tsc --noEmit && pnpm biome check src/lib src/types-progress.ts src/components/ui src/components/icons`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types-progress.ts frontend/src/lib frontend/src/components/icons frontend/src/components/ui
git -c commit.gpgsign=false commit -m "feat(frontend): primitives — BigInt-cents fmt\$, icons, ui

Resolves H4 from the design-spec critic review: fmt\$ no longer uses
parseFloat. Parses decimal strings into BigInt cents and formats with
thousand separators. Preserves precision for sums above 2^53 cents.

cumulative_cost_usd in ExtractionProgress changed to string so the
SSE precision contract holds end-to-end."
```

---

## Phase 3 — Stateless components

### Task 3.1: Copy six stateless components verbatim

**Files:**
- Create: `frontend/src/components/Header.tsx`, `UploadView.tsx`, `AgentTimeline.tsx`, `PeriodChipsBar.tsx`, `TransactionsTable.tsx`, `JSONViewer.tsx`
- Replace: `frontend/src/components/PeriodCard.tsx`

- [ ] **Step 1: Copy**

```bash
cp handoff_package/frontend/src/components/Header.tsx            frontend/src/components/Header.tsx
cp handoff_package/frontend/src/components/UploadView.tsx        frontend/src/components/UploadView.tsx
cp handoff_package/frontend/src/components/AgentTimeline.tsx     frontend/src/components/AgentTimeline.tsx
cp handoff_package/frontend/src/components/PeriodChipsBar.tsx    frontend/src/components/PeriodChipsBar.tsx
cp handoff_package/frontend/src/components/TransactionsTable.tsx frontend/src/components/TransactionsTable.tsx
cp handoff_package/frontend/src/components/JSONViewer.tsx        frontend/src/components/JSONViewer.tsx
cp handoff_package/frontend/src/components/PeriodCard.tsx        frontend/src/components/PeriodCard.tsx  # overwrites existing
```

- [ ] **Step 2: Verify `tsc --noEmit`**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: errors only about missing `./ResultsView`, `./ProcessingView`, `./ReviewModal` (will land in next tasks). No type errors in the six copied files.

### Task 3.2: Drop `ResultsView.tsx` with F2 (delete `aggregate()` and hero stats)

**Files:**
- Create: `frontend/src/components/ResultsView.tsx`

- [ ] **Step 1: Copy then edit**

```bash
cp handoff_package/frontend/src/components/ResultsView.tsx frontend/src/components/ResultsView.tsx
```

- [ ] **Step 2: Open `frontend/src/components/ResultsView.tsx` and remove the `aggregate()` helper + the hero `stat-strip` block**

Delete lines 20-31 (the `function aggregate(...)` block), and replace the `<div className="stat-strip" ...>` (~ lines 64-86 in the drop) with a minimal version that shows only `agg.reconciled / agg.total` from a direct compute. Concretely:

Replace this section near the top of the function body (originally `const agg = aggregate(result.periods); ...`) with:

```ts
  const totalPeriods = result.periods.length;
  const reconciledCount = result.periods.filter((p) => p.reconciliation.reconciled).length;
  const allReconciled = reconciledCount === totalPeriods;
  const needsReview = result.pending_review != null
    || result.periods.some((p) => (p.verifier?.suspects?.length ?? 0) > 0);
  const reviewPeriod = result.periods.find((p) => (p.verifier?.suspects?.length ?? 0) > 0);
```

And replace `<Chip kind="danger" label={\`${agg.total - agg.reconciled} of ${agg.total} not reconciled\`} />` with `<Chip kind="danger" label={\`${totalPeriods - reconciledCount} of ${totalPeriods} not reconciled\`} />`.

Replace the entire `<div className="stat-strip" style={{ marginBottom: 24 }}> … </div>` block with this minimal version (the only aggregate stats kept are reconciled-count and total-transactions, both computable in integer arithmetic — no parseFloat):

```tsx
      <div className="stat-strip" style={{ marginBottom: 24 }}>
        <div>
          <div className="stat-label">Periods</div>
          <div className="big">
            {reconciledCount}<span style={{ color: "var(--ink-3)", fontWeight: 400 }}>/{totalPeriods}</span>
          </div>
          <div className="t-caption" style={{ marginTop: 2 }}>reconciled</div>
        </div>
        <div>
          <div className="stat-label">Transactions</div>
          <div className="big tnum">
            {result.periods.reduce(
              (acc, p) => acc + p.summary.deposits_count + p.summary.withdrawals_count,
              0,
            ).toLocaleString()}
          </div>
          <div className="t-caption" style={{ marginTop: 2 }}>
            {result.periods.reduce((a, p) => a + p.summary.deposits_count, 0)} credits
            {" · "}
            {result.periods.reduce((a, p) => a + p.summary.withdrawals_count, 0)} debits
          </div>
        </div>
        <div>
          <div className="stat-label">Status</div>
          <div className="big" style={{ fontSize: "var(--text-base)", paddingTop: 6 }}>
            {allReconciled ? "All reconciled" : "Needs review"}
          </div>
        </div>
      </div>
```

Also remove the now-unused `fmt$short` import and any other unused symbol the tsc surfaces.

- [ ] **Step 3: Grep to confirm zero `parseFloat` survives in the file**

Run: `grep -n parseFloat frontend/src/components/ResultsView.tsx`
Expected: no output.

- [ ] **Step 4: tsc + biome**

Run: `cd frontend && pnpm tsc --noEmit && pnpm biome check src/components/ResultsView.tsx`
Expected: both clean.

### Task 3.3: Commit Phase 3

- [ ] **Step 1: Commit**

```bash
git add frontend/src/components
git -c commit.gpgsign=false commit -m "feat(frontend): stateless components from design drop

Drop Header, UploadView, AgentTimeline, PeriodChipsBar,
TransactionsTable, JSONViewer, ResultsView, PeriodCard from
handoff_package. ResultsView drops the float-based aggregate() helper
(H4 fix from critic): cross-period totals now use integer counts
only; per-period money stays a Decimal string formatted by fmt\$."
```

---

## Phase 4 — Backend SSE (parallel with Phases 1-3 / 5)

### Task 4.1: Write the failing contract test for `stream_graph_events`

**Files:**
- Create: `tests/api/test_extract_stream.py`

- [ ] **Step 1: Write the test file with three test cases**

Create `tests/api/test_extract_stream.py`:

```python
"""Contract tests for the single-pass SSE generator and POST /extract/stream.

Tests use a fake graph whose `astream_events` returns a scripted list of
event dicts, so we exercise the aggregation/encoding logic without
touching Anthropic.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, AsyncIterator

import pytest

from src.api.streaming import stream_graph_events


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

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        return {"final": self._final}


def _step_start(name: str) -> dict[str, Any]:
    return {"event": "on_chain_start", "name": name, "data": {"input": {}}, "tags": []}


def _step_end(name: str) -> dict[str, Any]:
    return {"event": "on_chain_end", "name": name, "data": {"output": {}}, "tags": []}


def _model_end(usage: dict[str, int], node: str) -> dict[str, Any]:
    class Out:
        usage_metadata = usage

    return {
        "event": "on_chat_model_end",
        "name": "ChatAnthropic",
        "data": {"output": Out()},
        "tags": [f"langgraph:node={node}"],
    }


@pytest.mark.asyncio
async def test_clean_run_emits_8_steps_in_order() -> None:
    """A clean Ixonia-like run emits 8 step_running + 8 step_done + 1 result + 1 done."""
    happy_path = [
        "ingest", "split_periods",
        "classify_layout", "extract_account", "extract_summary", "extract_transactions",
        "verifier", "reconcile",
    ]
    events: list[dict[str, Any]] = []
    for n in happy_path:
        events.append(_step_start(n))
        events.append(_step_end(n))
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "deadbeef", "errors": []})

    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t1"}})]

    step_events = [e for e in out if e["kind"] == "step"]
    assert len(step_events) == 16  # 8 running + 8 done
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
    step_running = [e for e in out if e["kind"] == "step" and e["state"] == "running"]
    step_done = [e for e in out if e["kind"] == "step" and e["state"] == "done"]
    assert len(step_running) == 1, "exactly one running emission for the lane"
    assert len(step_done) == 1, "exactly one done emission for the lane"
    assert step_running[0]["fanout"] == 1
    # 10 starts processed; final done sees count back at 0
    assert step_done[0]["step_id"] == "extract_account"


@pytest.mark.asyncio
async def test_cost_accumulates_as_decimal_string() -> None:
    """on_chat_model_end events sum into a 4dp decimal string."""
    events = [
        _step_start("extract_account"),
        _model_end({"input_tokens": 1000, "output_tokens": 200}, "extract_account"),
        _model_end({"input_tokens": 500, "output_tokens": 100}, "extract_account"),
        _step_end("extract_account"),
    ]
    graph = FakeGraph(events, final={"periods": [], "statement_sha256": "x", "errors": []})

    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t3"}})]
    costs = [e for e in out if e["kind"] == "cost"]
    assert len(costs) == 2
    assert all(isinstance(c["cumulative_cost_usd"], str) for c in costs)
    # second cost >= first cost (monotonic)
    assert Decimal(costs[1]["cumulative_cost_usd"]) >= Decimal(costs[0]["cumulative_cost_usd"])


@pytest.mark.asyncio
async def test_terminates_with_result_then_done() -> None:
    """Final two events are exactly result + done."""
    graph = FakeGraph([], final={"periods": [], "statement_sha256": "x", "errors": []})
    out = [ev async for ev in stream_graph_events(graph, {}, {"configurable": {"thread_id": "t4"}})]
    assert out[-2]["kind"] == "result"
    assert out[-1] == {"kind": "done"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_extract_stream.py -v`
Expected: collection error or 4× FAIL — `ModuleNotFoundError: src.api.streaming` (file does not exist yet).

### Task 4.2: Implement `src/api/streaming.py`

**Files:**
- Create: `src/api/streaming.py`

- [ ] **Step 1: Write the streaming generator**

Create `src/api/streaming.py`:

```python
"""SSE event generator over a single ``graph.astream_events`` invocation.

Phase 4 of `docs/superpowers/specs/2026-05-13-frontend-redesign-design.md`.

This module is pure async: no FastAPI, no HTTP. The router in
`src/api/routers/extract_stream.py` wraps these dicts into ``data:
{...}\\n\\n`` lines.

Server-side fan-out aggregation collapses ``Send``-fanned branches of
a step (e.g. 10 parallel ``extract_account`` invocations on Ixonia)
into one ``state:"running"`` + one ``state:"done"`` event per lane.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

from src.api.pricing import cost_for_node

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


async def stream_graph_events(
    graph: Any,
    initial_state: dict[str, Any],
    config: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
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
                    else:
                        yield {
                            "kind": "step",
                            "step_id": node,
                            "state": "running",
                            "progress": 0.0,
                            "elapsed_ms": _ts_ms() - step_started_at.get(node, _ts_ms()),
                            "fanout": running_count[node],
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
                        # Per-period state fold for verifier/reconcile node ends.
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
                    final_output = (ev.get("data") or {}).get("output") or {}
                    final_result = final_output.get("final", final_result)
            elif kind == "on_chat_model_end":
                usage = _usage_from_event(ev)
                node_tag = _node_tag_from_event(ev)
                if usage and node_tag:
                    cumulative_cost += cost_for_node(node_tag, usage)
                    yield {
                        "kind": "cost",
                        "cumulative_cost_usd": str(cumulative_cost.quantize(Decimal("0.0001"))),
                    }
    except Exception as exc:  # noqa: BLE001 — we want to ship the message and re-raise
        yield {"kind": "error", "message": str(exc)}
        yield {"kind": "done"}
        raise

    # If finalize never fired (graph paused at await_review etc.), `final_result`
    # is None and the consumer just sees an empty result envelope. The HTTP
    # handler will still resolve correctly because the body promise contains
    # whatever state the graph left behind.
    if final_result is None:
        # Try the explicit ainvoke fallback for the final.  This is cheap (no
        # second graph run): callers pre-compute and pass the final result via
        # the `_pre_final` private kwarg in the router when possible.
        final_result = initial_state.get("_pre_final")

    yield {"kind": "result", "result": _serialize_final(final_result)}
    yield {"kind": "done"}


def _usage_from_event(ev: dict[str, Any]) -> dict[str, int] | None:
    out = (ev.get("data") or {}).get("output")
    if out is None:
        return None
    meta = getattr(out, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    return {k: int(v) for k, v in meta.items() if isinstance(v, int)}


def _node_tag_from_event(ev: dict[str, Any]) -> str | None:
    """Pull the graph node id from the langgraph tag list."""
    for tag in ev.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("langgraph:node="):
            return tag.split("=", 1)[1]
    return None


def _period_states_from_verifier(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit kind:"period" events for verifier output (suspects > 0 → danger)."""
    out = (ev.get("data") or {}).get("output") or {}
    reports = out.get("verifier_reports") or []
    msgs: list[dict[str, Any]] = []
    for r in reports:
        chunk_id = getattr(r, "chunk_id", None) or (r.get("chunk_id") if isinstance(r, dict) else None)
        if chunk_id is None:
            continue
        suspects = getattr(r, "suspects", None) or (r.get("suspects") if isinstance(r, dict) else [])
        msgs.append(
            {"kind": "period", "chunk_id": chunk_id, "state": "danger" if suspects else "running"}
        )
    return msgs


def _period_states_from_reconcile(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit kind:"period" success/danger off reconciliation reducer output."""
    out = (ev.get("data") or {}).get("output") or {}
    recs = out.get("reconciliations") or []
    msgs: list[dict[str, Any]] = []
    for r in recs:
        chunk_id = getattr(r, "chunk_id", None) or (r.get("chunk_id") if isinstance(r, dict) else None)
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


def _serialize_final(final: Any) -> dict[str, Any] | None:
    """Convert an ExtractResult (or dict) to a JSON-serialisable dict."""
    if final is None:
        return None
    if hasattr(final, "model_dump"):
        return final.model_dump(mode="json")
    if isinstance(final, dict):
        return final
    return None
```

- [ ] **Step 2: Add `cost_for_node` helper to `src/api/pricing.py` if it doesn't exist**

Read `src/api/pricing.py`. If a function `cost_for_node(node_tag: str, usage: dict[str, int]) -> Decimal` is not already exported, add it. It must read the pricing table (already in `pricing.py` per phase-3 work) and return the cost for the given usage. Function signature must be exactly:

```python
def cost_for_node(node_tag: str, usage: dict[str, int]) -> Decimal:
    ...
```

If the function exists under a different name, alias it. Do NOT duplicate the pricing table — `streaming.py` imports it.

- [ ] **Step 3: Run the tests — should pass now**

Run: `uv run pytest tests/api/test_extract_stream.py -v`
Expected: all 4 tests PASS. If `cost_accumulates_as_decimal_string` fails because `cost_for_node` was missing, fix step 2 and re-run.

- [ ] **Step 4: Lint + typecheck**

Run: `uv run ruff check src/api/streaming.py && uv run mypy src/api/streaming.py`
Expected: both clean.

### Task 4.3: Write the `POST /extract/stream` router

**Files:**
- Create: `src/api/routers/extract_stream.py`
- Modify: `src/api/main.py:133` (one line — register router)

- [ ] **Step 1: Write the router**

Create `src/api/routers/extract_stream.py`:

```python
"""POST /extract/stream — single-pass SSE extraction endpoint.

Mirrors the validation logic of POST /extract (size, content-type, sha256,
temp-file lifecycle), then opens a ``StreamingResponse`` over
``src.api.streaming.stream_graph_events`` so the graph runs exactly once
and SSE events flow to the client as they happen.

The original POST /extract (JSON) endpoint stays for tests, the held-out
fixture runner, and as a degradation fallback for the frontend.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from src.api.logging import get_logger
from src.api.streaming import stream_graph_events

logger = get_logger(__name__)

router = APIRouter()

_MAX_PDF_BYTES = 80 * 1024 * 1024  # 80 MB
_MAX_OCR_BYTES = 5 * 1024 * 1024  # 5 MB
_PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


def _delete_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError as exc:
        logger.warning("extract_stream: could not delete temp file %s: %s", path, exc)


@router.post("/extract/stream")
async def extract_stream(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    ocr_text: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    """Stream extraction progress + final ExtractResult as SSE."""
    if file.content_type not in _PDF_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {file.content_type!r}")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum upload size of {_MAX_PDF_BYTES} bytes ({len(pdf_bytes)} received).",
        )

    digest = sha256(pdf_bytes).hexdigest()

    pdf_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        pdf_tmp.write(pdf_bytes)
        pdf_tmp.flush()
    finally:
        pdf_tmp.close()
    pdf_path = pdf_tmp.name
    background_tasks.add_task(_delete_file, pdf_path)

    txt_path: str | None = None
    if ocr_text is not None:
        ocr_bytes = await ocr_text.read()
        if len(ocr_bytes) > _MAX_OCR_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"OCR text file exceeds maximum size of {_MAX_OCR_BYTES} bytes.",
            )
        ocr_tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        try:
            ocr_tmp.write(ocr_bytes)
            ocr_tmp.flush()
        finally:
            ocr_tmp.close()
        txt_path = ocr_tmp.name
        background_tasks.add_task(_delete_file, txt_path)

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
        "run_name": f"unknown:{digest[:8]}",
        "tags": ["extract", "stream"],
        "metadata": {"statement_hash": digest},
        "recursion_limit": 50,
    }

    graph = request.app.state.graph
    logger.info("extract_stream: starting thread_id=%s sha256=%s…", thread_id, digest[:16])

    async def event_source() -> "asyncio.AsyncIterator[bytes]":
        try:
            async for payload in stream_graph_events(graph, initial_state, config):
                yield f"data: {json.dumps(payload, default=str)}\n\n".encode("utf-8")
        except asyncio.CancelledError:
            logger.info("extract_stream: client disconnected thread_id=%s", thread_id)
            raise

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx / proxies — don't buffer
        },
    )
```

- [ ] **Step 2: Register the router in `src/api/main.py`**

Edit `src/api/main.py`. Find the line `from src.api.routers.extract import router as extract_router` and immediately below it add:

```python
from src.api.routers.extract_stream import router as extract_stream_router
```

Then find `application.include_router(extract_router)` and immediately below it add:

```python
    application.include_router(extract_stream_router)
```

- [ ] **Step 3: Lint + typecheck**

Run: `uv run ruff check src/api/routers/extract_stream.py src/api/main.py && uv run mypy src/api/routers/extract_stream.py src/api/main.py`
Expected: both clean.

- [ ] **Step 4: Run all backend tests**

Run: `uv run pytest -q tests/api`
Expected: all green (including the 4 new SSE tests + the existing extract / reviews tests).

### Task 4.4: Live smoke test against the running API

- [ ] **Step 1: Start the server**

Run: `uv run uvicorn src.api.main:app --reload --port 8000`

(Keep this running in another shell. If `ANTHROPIC_API_KEY` is set you can test against a real graph; otherwise the smoke test below will fail at the model-call step — that's fine, you just need to see the SSE byte stream start.)

- [ ] **Step 2: Curl the stream**

In a second shell:

```bash
curl -N -X POST http://localhost:8000/extract/stream \
  -F file=@Task/Binder2_Redacted.pdf \
  -F ocr_text=@Task/ixonia_binder2_ocr.txt
```

Expected (with an API key): SSE lines of the form `data: {"kind":"step","step_id":"ingest","state":"running",...}`, ending with `data: {"kind":"done"}`. Without an API key: stream starts (`ingest` running/done) then errors out cleanly with `data: {"kind":"error","message":"..."}` followed by `data: {"kind":"done"}`.

- [ ] **Step 3: Commit Phase 4**

```bash
git add src/api/streaming.py src/api/routers/extract_stream.py src/api/main.py tests/api/test_extract_stream.py src/api/pricing.py
git -c commit.gpgsign=false commit -m "feat(api): single-pass SSE extraction stream (POST /extract/stream)

Adds streaming.py — pure async generator over graph.astream_events that
collapses Send fan-out into per-step running/done transitions and sums
LLM cost as a 4dp decimal string. Adds extract_stream router that opens
a StreamingResponse with no-cache + X-Accel-Buffering: no headers.

Existing POST /extract (JSON) is untouched for test/eval compat.

Closes critic-review HIGH H1 (dual invocation) and H2 (fan-out spam)."
```

---

## Phase 5 — Frontend state machine

### Task 5.1: Drop `ProcessingView` with side-step indicator + string-cost display

**Files:**
- Create: `frontend/src/components/ProcessingView.tsx`

- [ ] **Step 1: Copy**

```bash
cp handoff_package/frontend/src/components/ProcessingView.tsx frontend/src/components/ProcessingView.tsx
```

- [ ] **Step 2: Apply F5 (side-step indicator) and string-cost display**

Edit `frontend/src/components/ProcessingView.tsx`:

a) Replace `${progress.cumulative_cost_usd.toFixed(4)}` with `${progress.cumulative_cost_usd}` (the SSE already sends 4dp string).

b) Below the existing `<SectionLabel>Agent pipeline</SectionLabel>` + `<AgentTimeline ... />` block, add a side-step indicator that renders when the active step is **not** in `AGENT_STEPS`. Append this block right before the `progress.thread_id` block:

```tsx
      {!AGENT_STEPS.some((s) => s.id === progress.active_step) && progress.active_step !== "" && (
        <div
          style={{
            marginTop: 14,
            padding: "8px 12px",
            borderRadius: "var(--radius-2)",
            background: "var(--surface-2)",
            border: "1px solid var(--border-1)",
            fontSize: 12,
            color: "var(--ink-3)",
          }}
        >
          <span className="mono" style={{ color: "var(--ink-2)" }}>{progress.active_step}</span>
          {" — "}
          {progress.active_step === "critic" && "Critic loop reviewing extraction…"}
          {progress.active_step === "apply_critic_hint" && "Applying critic hint…"}
          {progress.active_step === "await_review" && "Awaiting human review…"}
          {progress.active_step === "merge_state" && "Merging fan-out results…"}
          {progress.active_step === "finalize" && "Finalising response…"}
        </div>
      )}
```

- [ ] **Step 3: Verify tsc**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean (after Task 2.2's `cumulative_cost_usd: string` change in `types-progress.ts`).

### Task 5.2: Drop `ReviewModal` with F4 (REASON_LABEL[reason])

**Files:**
- Replace: `frontend/src/components/ReviewModal.tsx`

- [ ] **Step 1: Copy**

```bash
cp handoff_package/frontend/src/components/ReviewModal.tsx frontend/src/components/ReviewModal.tsx
```

- [ ] **Step 2: Apply F4 — read the period's `pending_review.reason` and pass it to the component**

The component receives `period: PeriodResult` but `pending_review.reason` lives on `ExtractResult.pending_review`. Two edits:

a) Add an optional prop:

Change the `interface Props` block:

```tsx
interface Props {
  period: PeriodResult;
  /** When the pause carries a reason ("suspects_exceeded" | "cost_ceiling_exceeded" | "retry_exhausted") */
  pauseReason?: "suspects_exceeded" | "cost_ceiling_exceeded" | "retry_exhausted";
  /** When provided, used as the source-of-truth suspect list. Otherwise reads period.verifier.suspects. */
  suspects?: Suspect[];
  busy?: boolean;
  onClose: () => void;
  onSubmit: (corrections: TransactionCorrection[], force: boolean) => void | Promise<void>;
}
```

Change the component signature to destructure `pauseReason`:

```tsx
export function ReviewModal({ period, pauseReason = "suspects_exceeded", suspects, busy, onClose, onSubmit }: Props) {
```

Replace line 79 (`{REASON_LABEL.suspects_exceeded} {period.chunk_id}`) with:

```tsx
                {REASON_LABEL[pauseReason]} {period.chunk_id}
```

- [ ] **Step 3: Verify tsc**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean.

### Task 5.3: Replace `App.tsx` with the state-machine version

**Files:**
- Replace: `frontend/src/App.tsx`

- [ ] **Step 1: Copy**

```bash
cp handoff_package/frontend/src/App.tsx frontend/src/App.tsx
```

- [ ] **Step 2: Adjust three drift spots in the drop**

Edit `frontend/src/App.tsx`:

a) Replace the `cost={...}` prop on `<Header ... />` (line ~67 in the drop) with:

```tsx
        cost={phase !== "upload" ? progress.cumulative_cost_usd : null}
```

(Header's `cost` prop must accept `string | null`. If the drop's `Header.tsx` types it as `number | null | undefined`, also edit `frontend/src/components/Header.tsx` to change the prop type to `string | null | undefined` and the display line to `{cost ?? "—"}` — leaving the `$` prefix logic intact if any. Check `Header.tsx` first; many drops type it as `number`.)

b) Add the `pauseReason` prop to the `<ReviewModal …/>` call near the bottom:

```tsx
        <ReviewModal
          period={reviewing}
          pauseReason={result?.pending_review?.reason ?? "suspects_exceeded"}
          busy={submitBusy}
          onClose={() => setReviewing(null)}
          onSubmit={handleReviewSubmit}
        />
```

c) The `<ResultsView ... costUsd={progress.cumulative_cost_usd || undefined}` (number) is now incompatible with string cost. Edit it to:

```tsx
          <ResultsView
            result={result}
            filename={filename ?? undefined}
            wallClockText={undefined}
            costUsd={progress.cumulative_cost_usd || undefined}
            onReview={setReviewing}
          />
```

and update `ResultsView`'s `costUsd?: number` prop type to `costUsd?: string` (the display line `${costUsd.toFixed(4)}` becomes `${costUsd}` — already 4dp from the SSE).

- [ ] **Step 3: Resolve any remaining tsc errors**

Run: `cd frontend && pnpm tsc --noEmit`
Walk through errors top-to-bottom. Most will be prop-type drift between `string` (new cost type) and `number` (old type). Fix at the prop-type source.

- [ ] **Step 4: Manual smoke (inert SSE — no live wiring yet)**

Run: `cd frontend && pnpm dev` then upload `Task/Binder2_Redacted.pdf`. Expected:
- Upload view renders, file drop works.
- Submitting moves to processing view (timeline visible but inert — no SSE wiring yet).
- On graph completion (~30-60s), results view shows all 10 periods (assuming a clean Ixonia run with an API key).
- Clicking "Open review" on a danger period opens the modal. Force-finalize submits and updates the displayed result.

- [ ] **Step 5: Commit Phase 5**

```bash
git add frontend/src/App.tsx frontend/src/components/ProcessingView.tsx frontend/src/components/ReviewModal.tsx frontend/src/components/Header.tsx frontend/src/components/ResultsView.tsx
git -c commit.gpgsign=false commit -m "feat(frontend): state-machine app + side-step indicator + cost-string display

App.tsx becomes a 3-phase state machine (upload -> processing -> results).
ProcessingView renders a small indicator for graph nodes outside the
8-lane happy path (L1 fix from critic). ReviewModal renders the correct
reason label for all three PendingReview.reason values (L3 fix).
cumulative_cost_usd flows as a decimal string end-to-end."
```

---

## Phase 6 — SSE client wiring

### Task 6.1: Add `extractStatementStreaming` to `api.ts`

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Append the streaming function and supporting types**

Edit `frontend/src/api.ts`. After the existing `extractStatement` function, add:

```ts
import type { AgentStepProgress, ExtractionProgress, PeriodVisualState, ProgressCallback } from "./types-progress";
import { AGENT_STEPS } from "./lib/agentSteps";

type StreamEvent =
  | { kind: "step"; step_id: string; state: "running" | "done" | "error"; progress: number; elapsed_ms: number; fanout?: number; side?: boolean }
  | { kind: "cost"; cumulative_cost_usd: string }
  | { kind: "period"; chunk_id: string; state: PeriodVisualState }
  | { kind: "result"; result: ExtractResult }
  | { kind: "done" }
  | { kind: "error"; message: string };

function emptyProgress(): ExtractionProgress {
  return {
    thread_id: "",
    active_step: AGENT_STEPS[0].id,
    cumulative_cost_usd: "0.0000",
    steps: AGENT_STEPS.map((s) => ({ step_id: s.id, state: "idle", progress: 0, elapsed_ms: 0 })),
    period_states: {},
  };
}

function parseSseEvent(raw: string): StreamEvent | null {
  if (!raw.startsWith("data:")) return null;
  const json = raw.slice(5).trim();
  if (json === "") return null;
  try {
    const obj = JSON.parse(json) as { kind?: unknown };
    if (typeof obj.kind !== "string") {
      console.warn("parseSseEvent: missing 'kind'", json);
      return null;
    }
    return obj as StreamEvent;
  } catch (err) {
    console.warn("parseSseEvent: invalid JSON", json, err);
    return null;
  }
}

function fold(prev: ExtractionProgress, ev: StreamEvent): ExtractionProgress {
  if (ev.kind === "step") {
    if (ev.side === true) {
      // Side-step: drive the active-step indicator only.
      return { ...prev, active_step: ev.state === "running" ? ev.step_id : prev.active_step };
    }
    const idx = prev.steps.findIndex((s) => s.step_id === ev.step_id);
    if (idx < 0) return prev;
    const updated: AgentStepProgress = {
      step_id: ev.step_id,
      state: ev.state,
      progress: ev.progress,
      elapsed_ms: ev.elapsed_ms,
      fanout: ev.fanout,
    };
    const steps = prev.steps.slice();
    steps[idx] = updated;
    return {
      ...prev,
      steps,
      active_step: ev.state === "running" ? ev.step_id : prev.active_step,
    };
  }
  if (ev.kind === "cost") {
    return { ...prev, cumulative_cost_usd: ev.cumulative_cost_usd };
  }
  if (ev.kind === "period") {
    return { ...prev, period_states: { ...prev.period_states, [ev.chunk_id]: ev.state } };
  }
  return prev;
}

/**
 * POST multipart to /extract/stream, parse SSE, accumulate progress.
 * Returns the final ExtractResult or throws ApiError.
 *
 * If the new endpoint returns 404 (deploy lag), falls back to the
 * JSON `extractStatement` so the UI still works (graceful degradation).
 */
export async function extractStatementStreaming(
  pdfFile: File,
  ocrFile?: File,
  onProgress?: ProgressCallback,
  signal?: AbortSignal,
): Promise<ExtractResult> {
  const form = new FormData();
  form.append("file", pdfFile);
  if (ocrFile !== undefined) form.append("ocr_text", ocrFile);

  const response = await fetch(`${API_BASE}/extract/stream`, {
    method: "POST",
    body: form,
    signal,
  });

  if (response.status === 404) {
    console.warn("extractStatementStreaming: /extract/stream not found, falling back to /extract");
    return extractStatement(pdfFile, ocrFile);
  }
  if (!response.ok) {
    const text = await response.text();
    throw buildApiError(response.status, text);
  }
  if (response.body === null) {
    throw new ApiError(500, "No response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let progress = emptyProgress();
  if (onProgress) onProgress(progress);

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line.
    let idx = buf.indexOf("\n\n");
    while (idx !== -1) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = parseSseEvent(raw);
      if (ev !== null) {
        if (ev.kind === "result") {
          return ev.result;
        }
        if (ev.kind === "done") {
          // No result event was emitted before done — protocol violation.
          throw new ApiError(500, "SSE stream ended without a result event");
        }
        if (ev.kind === "error") {
          throw new ApiError(500, ev.message);
        }
        progress = fold(progress, ev);
        if (onProgress) onProgress(progress);
      }
      idx = buf.indexOf("\n\n");
    }
  }
  throw new ApiError(500, "SSE stream closed before a result event");
}
```

- [ ] **Step 2: Verify tsc**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean.

### Task 6.2: Switch `App.tsx` to use `extractStatementStreaming` with AbortController

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Switch the import and call site**

Edit `frontend/src/App.tsx`:

a) Change `import { ApiError, extractStatement, submitReview } from "./api";` to:

```tsx
import { ApiError, extractStatementStreaming, submitReview } from "./api";
```

b) Inside the component body, add an AbortController ref:

```tsx
import { useCallback, useRef, useState } from "react";
// ...
  const abortRef = useRef<AbortController | null>(null);
```

c) In `handleSubmit`, instantiate the controller, pass its signal, and replace `extractStatement(...)` with `extractStatementStreaming(...)`:

```tsx
  async function handleSubmit(pdf: File, ocr: File | null) {
    setError(null);
    setFilename(pdf.name);
    setProgress(emptyProgress());
    setPhase("processing");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const r = await extractStatementStreaming(pdf, ocr ?? undefined, onProgress, controller.signal);
      setResult(r); setPhase("results");
    } catch (e) {
      if (controller.signal.aborted) {
        setPhase("upload");
        return;
      }
      const msg = e instanceof ApiError ? e.message : "Network error — is the API running?";
      setError(msg); setPhase("upload");
    }
  }
```

d) Wire Cancel to abort:

```tsx
        {phase === "processing" && (
          <ProcessingView
            progress={progress}
            periods={Object.keys(progress.period_states).map((id) => ({ id, month: "Unknown", last4: "" }))}
            onCancel={() => abortRef.current?.abort()}
          />
        )}
```

(The `periods` prop is now derived from `progress.period_states` keys, which the SSE populates as `kind:"period"` events arrive.)

- [ ] **Step 2: Verify tsc + biome**

Run: `cd frontend && pnpm tsc --noEmit && pnpm biome check src/`
Expected: both clean.

- [ ] **Step 3: E2E manual smoke against running backend**

In two shells:

Shell A: `uv run uvicorn src.api.main:app --reload --port 8000`
Shell B: `cd frontend && pnpm dev` (port 5173)

Then in the browser at http://localhost:5173:

1. Upload `Task/Binder2_Redacted.pdf` + `Task/ixonia_binder2_ocr.txt`.
2. **Verify timeline lights up lane-by-lane in real time** as the graph progresses. `ingest` runs first; `extract_account/summary/transactions` show `fanout` 1→10 then go done.
3. **Verify cost ticker counts up** with 4dp precision.
4. **Verify period chips appear** as `reconcile` finishes.
5. On completion, results view shows all 10 reconciled periods.
6. Open Network tab. Repeat the upload, click **Cancel** mid-flight. The `POST /extract/stream` request should show `(cancelled)` and the UI returns to upload phase.

- [ ] **Step 4: Commit Phase 6**

```bash
git add frontend/src/api.ts frontend/src/App.tsx
git -c commit.gpgsign=false commit -m "feat(frontend): wire SSE client for live agent timeline

extractStatementStreaming() POSTs multipart to /extract/stream, reads
the response body as SSE (fetch + ReadableStream — EventSource doesn't
support POST), folds events into ExtractionProgress, and resolves on
kind:result. AbortController lets the user Cancel mid-extract.
On 404 from the new endpoint, falls back to the JSON /extract path."
```

---

## Phase 7 — Critic + cleanup

### Task 7.1: Delete stale frontend files

**Files:**
- Delete: `frontend/src/components/UploadForm.tsx`
- Delete: `frontend/src/components/ReconciliationBanner.tsx`

- [ ] **Step 1: Delete**

```bash
rm frontend/src/components/UploadForm.tsx
rm frontend/src/components/ReconciliationBanner.tsx
```

- [ ] **Step 2: Verify nothing imports them**

Run: `grep -rn "UploadForm\|ReconciliationBanner" frontend/src`
Expected: no output.

- [ ] **Step 3: tsc + biome**

Run: `cd frontend && pnpm tsc --noEmit && pnpm biome check src/`
Expected: both clean.

### Task 7.2: Full pre-commit check

- [ ] **Step 1: Backend**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`
Expected: all clean / green.

- [ ] **Step 2: Frontend**

Run: `cd frontend && pnpm biome check . && pnpm tsc --noEmit`
Expected: both clean.

- [ ] **Step 3: Commit cleanup**

```bash
git add -A
git -c commit.gpgsign=false commit -m "chore(frontend): drop UploadForm and ReconciliationBanner

Functionality replaced by UploadView + PeriodCard's inline danger
state in the redesign. No remaining references."
```

### Task 7.3: Critic final pass

- [ ] **Step 1: Run the critic subagent**

Use the Agent tool with `subagent_type: "critic"`. Prompt:

```
Review the full diff vs main of the frontend-redesign + SSE work.
Score against the 12 rules in CLAUDE.md. Re-run lint + mypy + pytest
yourself — do not trust prior claims. The spec is at
docs/superpowers/specs/2026-05-13-frontend-redesign-design.md and the
plan at docs/superpowers/plans/2026-05-13-frontend-redesign.md.
Produce the JSON verdict per .claude/agents/critic.md output contract.
If any finding is HIGH severity, name the agent to fix it.
```

- [ ] **Step 2: Address any HIGH findings**

If the critic returns HIGH findings, dispatch the named agent for each (likely `react-engineer`, `fastapi-engineer`, or `langgraph-engineer`). Re-run the critic until verdict is `approve`.

- [ ] **Step 3: Final smoke**

Repeat Phase 6 Task 6.2 Step 3 once more — full Ixonia run through the live UI, observe timeline + cost + all 10 reconciled periods on the results view.

---

## Spec coverage check

Each spec section maps to:

| Spec §           | Task(s)                  |
|------------------|--------------------------|
| §1 Goal          | acceptance via Task 7.3  |
| §2 H1/H2/H3/H4   | T2.2 (H4), T3.2 (H4), T4.2 (H1+H2), spec §3 obsoletes H3 |
| §3 architecture  | T4.2, T4.3, T6.1         |
| §4.1 request     | T4.3                     |
| §4.2 response    | T4.2 (generator), T4.1 tests, T6.1 (parser) |
| §4.3 fan-out     | T4.2 + T4.1 test 2       |
| §4.4 per-period  | T4.2 helpers + T4.1 test (suspect → danger is exercised via reconcile/verifier helpers; explicit test deferred to live smoke) |
| §4.5 cost        | T4.2 + T4.1 test 3       |
| §4.6 cancel      | T4.3 (try/except in router) + T6.2 (AbortController) |
| §5 F1            | T2.2                     |
| §5 F2            | T3.2                     |
| §5 F3            | T1.1                     |
| §5 F4            | T5.2                     |
| §5 F5            | T2.2 (docstring) + T5.1 (indicator) |
| §5 F6            | T6.1                     |
| §6 tests         | T4.1 + T6.1 `parseSseEvent` |
| §7 phases        | this whole file          |
| §8 files         | each task's file table   |
| §9 OOS           | enforced by task scope   |
| §10 disposition  | spec doc                 |
| §11 risks        | inline mitigations       |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-frontend-redesign.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task using `superpowers:subagent-driven-development`. Each phase is owned by the right specialist (`langgraph-engineer` for Phase 0 + 4 collaboration, `react-engineer` for Phases 1-3 + 5-6, `fastapi-engineer` for Phase 4, `critic` for Phase 7). Fast iteration with two-stage review.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoints between phases.

Which approach?

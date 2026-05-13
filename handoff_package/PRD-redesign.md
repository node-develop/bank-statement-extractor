# PRD — Bank Statement Extractor frontend redesign

**Document version:** 1.0
**Date:** 2026-05-13
**Owner:** dev@artka.dev
**Scope:** Replace the current Bootstrap-flavored React frontend
with the Bank Statement Extractor design system (purple accent,
Inter / JetBrains Mono, agent timeline, JSON viewer, review modal),
and wire it to a streaming backend so the agent timeline is live.

**Implementation order:** P1 → P2 → P3 → (P4 + P5 in parallel) → P6.

**Total estimate:** ~14 hours across 6 phases, with two distinct
agent specialisations (`react-engineer`, `fastapi-engineer` /
`langgraph-engineer`).

**Companion docs:**
- `README.md` — how to drop this package into the repo.
- `agents/01..05-*.md` — one prompt per phase, drop-in for Claude
  Code.

---

## 0 · Why we are doing this

The current frontend (`bank-statement-analizer/frontend/src/`) is
functional but undesigned: inline styles, system-font stack, Bootstrap
colors. The product is a multi-agent pipeline whose **value
proposition is observability** — the user uploads a PDF and watches
named agents work through 10 periods of statement data. The current
UI does not surface that work at all; it blocks on the request and
dumps results when done.

This PRD lands:

1. A coherent visual language (Bank Statement Extractor design
   system — purple accent, restrained, technical).
2. Component re-skin with TSX components that match the existing
   type contracts in `frontend/src/types.ts`.
3. A live **agent timeline** that animates while the LangGraph
   pipeline runs, driven by SSE.
4. A **state machine** in App.tsx: `upload → processing → results`,
   with the review modal as an overlay.

---

## 1 · Current state (immutable contracts you build on)

### 1.1 Repo layout

```
frontend/
├── index.html
├── package.json                 # vite + react 19 + ts + biome
├── tsconfig.json
├── vite.config.ts
├── public/                      # empty
└── src/
    ├── main.tsx
    ├── App.tsx                  # inline styles, ~150 LoC
    ├── api.ts                   # extractStatement, submitReview, getReview
    ├── types.ts                 # ExtractResult, PeriodResult, Suspect, …
    ├── index.css
    ├── vite-env.d.ts
    └── components/
        ├── UploadForm.tsx
        ├── PeriodCard.tsx
        ├── ReconciliationBanner.tsx
        └── ReviewModal.tsx
```

### 1.2 Existing types you MUST consume

`src/types.ts` already defines: `Period`, `Account`, `Summary`,
`Transaction`, `Reconciliation`, `Suspect`, `Gap`, `VerifierReport`,
`PendingReview`, `TransactionCorrection`, `PeriodResult`,
`ExtractResult`. **Do not redefine these.** The new TSX components
in this package consume them by import.

### 1.3 Precision contract (carried over)

> all monetary fields are JSON strings (e.g. "597068.70"). Do NOT
> parseFloat them. Display as-is, prefix "$" only in the UI layer.

The helper `fmt$()` in `lib/agentSteps.ts` is the *only* place that
parses money strings — into a `toLocaleString` for display. Never
parse them anywhere else.

### 1.4 Existing API client

`src/api.ts` already exports `extractStatement(pdf, ocr?)`,
`submitReview(id, payload)`, `getReview(id)`, and `ApiError`. Phase 6
adds a third argument `onProgress` to `extractStatement` for SSE
streaming.

---

## 2 · Phase 1 — Foundation: tokens, fonts, assets (≈ 1h)

### 2.1 Files to change

| File                                    | Action                                                     |
|-----------------------------------------|------------------------------------------------------------|
| `frontend/src/styles/tokens.css`        | NEW — drop from package                                    |
| `frontend/src/styles/components.css`    | NEW — drop from package                                    |
| `frontend/public/{logo,mark,wordmark-short}.svg` | NEW — drop from package                          |
| `frontend/index.html`                   | Add Google Fonts `<link>` in `<head>`                      |
| `frontend/src/main.tsx`                 | Import tokens.css and components.css **before** index.css  |
| `frontend/src/index.css`                | Strip to empty (or delete)                                 |

### 2.2 Acceptance criteria

- `pnpm dev` runs.
- The app loads with Inter font visible in the placeholder text.
- `--accent` CSS variable resolves to `#5B33F0` in DevTools on
  `document.documentElement`.
- `frontend/public/logo.svg` renders at `/logo.svg`.
- No console errors.

### 2.3 Agent: `react-engineer`. Prompt: `agents/01-foundation.md`.

---

## 3 · Phase 2 — Primitives: types, icons, ui (≈ 1.5h)

### 3.1 Files to change

| File                                                   | Action |
|--------------------------------------------------------|--------|
| `frontend/src/types-progress.ts`                       | NEW — drop from package |
| `frontend/src/types.ts`                                | MERGE — append the contents of `types-progress.ts` exports at the bottom. (Or keep the separate file and import from it everywhere.) |
| `frontend/src/lib/agentSteps.ts`                       | NEW — drop |
| `frontend/src/components/icons/index.tsx`              | NEW — drop |
| `frontend/src/components/ui/{Button,Chip,SectionLabel}.tsx` | NEW — drop |

### 3.2 Acceptance criteria

- `pnpm tsc --noEmit` clean — no missing types, no unused imports.
- Importing `Button` from `./components/ui/Button` works in a
  scratch render.
- `pnpm biome check src/` passes (drop files match repo's biome
  config — single-quote / 2-space etc.).

### 3.3 Agent: `react-engineer`. Prompt: `agents/02-primitives.md`.

---

## 4 · Phase 3 — Stateless components (≈ 3h)

### 4.1 Files to change

Drop these from package, replacing existing where noted:

| File                                                   | Action |
|--------------------------------------------------------|--------|
| `frontend/src/components/Header.tsx`                   | NEW |
| `frontend/src/components/UploadView.tsx`               | NEW (replaces `UploadForm.tsx` in next phase) |
| `frontend/src/components/AgentTimeline.tsx`            | NEW |
| `frontend/src/components/PeriodChipsBar.tsx`           | NEW |
| `frontend/src/components/TransactionsTable.tsx`        | NEW |
| `frontend/src/components/PeriodCard.tsx`               | REPLACE |
| `frontend/src/components/JSONViewer.tsx`               | NEW |
| `frontend/src/components/ReconciliationBanner.tsx`     | DELETE (role moved into PeriodCard) |

### 4.2 Acceptance criteria

- `pnpm tsc --noEmit` clean.
- A storybook-like manual test: temporarily mount each component in
  `App.tsx` with fixture data (a single `PeriodResult` from
  `tests/fixtures/`) and verify visually. Then revert.
- `PeriodCard` renders both reconciled and unreconciled variants
  correctly.
- `TransactionsTable` highlights suspect rows (use a `PeriodResult`
  with a non-empty `verifier.suspects`).
- `JSONViewer` "Copy JSON" actually writes to the clipboard.

### 4.3 Agent: `react-engineer`. Prompt: `agents/03-stateless.md`.

---

## 5 · Phase 4 — Backend streaming (parallel with P5; ≈ 3h)

### 5.1 What we add

A new SSE endpoint that streams progress events while the LangGraph
run is in flight. The existing `POST /extract` stays — it now also
returns a `thread_id` early so the client can subscribe to the
stream while still awaiting the final response. Use LangGraph's
built-in `graph.astream_events(input, config, version="v2")`.

### 5.2 New files

```
src/api/routers/extract_stream.py   # NEW — SSE endpoint
src/api/streaming.py                # NEW — astream_events → SSE encoder
```

### 5.3 Endpoint

```
GET /extract/stream/{thread_id}
  → text/event-stream
  → events: data: <json>\n\n
```

Event payload shape (matches `AgentStepProgress` + a "period_state"
variant):

```jsonc
// Step transition
{"kind": "step", "step_id": "extract_account", "state": "running", "progress": 0.0, "elapsed_ms": 50, "fanout": 10}

// Cost update
{"kind": "cost", "cumulative_cost_usd": 0.1834}

// Per-period state transition
{"kind": "period", "chunk_id": "period_03", "state": "running"}

// Terminal
{"kind": "done"}
```

### 5.4 Mapping `astream_events` → our events

LangGraph emits events like:

- `on_chain_start` with `name == "extract_account"` → emit
  `{kind:"step", step_id:"extract_account", state:"running"}`
- `on_chain_end` with the same `name` → emit
  `{state:"done"}`
- `on_chain_*` for the parent fan-out `Send` (per-period) → bump
  `fanout`
- After each LLM-using node, sum `usage_metadata` against
  `src/api/pricing.py` and emit a `cost` event.

### 5.5 Acceptance criteria

- `curl -N http://localhost:8000/extract/stream/<tid>` against a
  running extract prints SSE events terminated by `{"kind":"done"}`.
- Total cost in the stream matches the value stored on the final
  `ExtractResult`.
- All 8 step transitions are emitted in order for a clean Ixonia
  run; period_states light up at the right node boundaries.
- The endpoint closes cleanly on client disconnect (no zombie
  generators).
- `pytest tests/api/test_extract_stream.py` covers: clean run, run
  with verifier suspects (period_states transition to "danger"),
  client disconnect mid-stream.

### 5.6 Agents: `fastapi-engineer` + `langgraph-engineer`. Prompt:
`agents/04-backend-streaming.md`.

---

## 6 · Phase 5 — Frontend state machine (parallel with P4; ≈ 2h)

### 6.1 Files to change

| File                                       | Action |
|--------------------------------------------|--------|
| `frontend/src/components/ProcessingView.tsx` | NEW — drop from package |
| `frontend/src/components/ResultsView.tsx`    | NEW — drop from package |
| `frontend/src/components/ReviewModal.tsx`    | REPLACE — drop from package |
| `frontend/src/components/UploadForm.tsx`     | DELETE |
| `frontend/src/App.tsx`                       | REPLACE — drop from package |

The drop is a near-complete App.tsx; the only TODO marked inline is
the `periods=[]` prop on `ProcessingView` — Phase 6 fills it from
the period_state events.

### 6.2 Acceptance criteria

- `pnpm tsc --noEmit` clean.
- `pnpm dev` shows the upload view; submitting a file moves to the
  processing view (timeline visible but inert without SSE — that's
  OK at this stage); on completion lands on the results view.
- Review modal opens from the danger banner and submits via
  `submitReview`.
- `pnpm biome check src/` passes.

### 6.3 Agent: `react-engineer`. Prompt: `agents/03-stateless.md` /
`agents/05-state-machine.md`.

---

## 7 · Phase 6 — Frontend SSE wiring (≈ 1.5h)

### 7.1 Files to change

| File              | Action |
|-------------------|--------|
| `frontend/src/api.ts` | Add third optional `onProgress` arg to `extractStatement`. Open an `EventSource` against `/extract/stream/{tid}` and dispatch to the callback. |
| `frontend/src/App.tsx` | Maintain a periods list derived from `kind:"period"` events (chunks discovered on the fly) and pass to `ProcessingView`. |

### 7.2 EventSource shape

```ts
export async function extractStatement(
  pdf: File,
  ocr?: File,
  onProgress?: ProgressCallback,
): Promise<ExtractResult> {
  // 1. POST /extract starts, returns headers w/ X-Thread-Id
  // 2. Open EventSource(`/extract/stream/${tid}`) on receipt
  // 3. Aggregate events into ExtractionProgress, call onProgress
  // 4. await the original POST promise, return its body
}
```

Backend must set `X-Thread-Id` header on the initial 200 response
chunk so the client knows the thread_id before the body completes.

### 7.3 Acceptance criteria

- During an active extract: agent timeline lanes light up in order;
  the active step indicator changes; cost ticker counts up.
- On `kind:"done"` the EventSource closes and the final
  `ExtractResult` is rendered.
- If the user clicks "Cancel" mid-extract, the EventSource closes
  and any pending POST is aborted via `AbortController`.
- `pnpm tsc --noEmit` clean.
- E2E smoke test (manual): upload Ixonia sample → see timeline
  advance → land on results with all 10 periods.

### 7.4 Agent: `react-engineer`. Prompt: `agents/05-state-machine.md`
(continued) or a dedicated `agents/06-sse-client.md` if you prefer
to split the task.

---

## 8 · Cross-cutting requirements

### 8.1 Layer boundaries

- Graph nodes never import from `src/api/*`. (Existing rule —
  preserved.)
- Frontend `App.tsx` never reads/writes to the LangGraph
  checkpointer directly; the only API surface is `api.ts`.

### 8.2 Style discipline

- **No emoji.** Anywhere. Not in copy, not in chips, not in
  loading states.
- **No inline styles for layout** — use the classes from
  `components.css`. Inline styles are only OK for one-off cosmetic
  positioning that doesn't recur (e.g. a single `flex: 1` spacer).
- **No new colors.** If you need a hue that isn't in tokens.css,
  pause and ask whether it should be added as a token first.
- **No gradients.** Beyond the existing `--shadow-flagship` and
  the optional dark-hero radial in `.hero-dark`.
- **No Tailwind / Mantine / etc.** Pure CSS classes + CSS custom
  properties, as the design system ships.

### 8.3 Naming

- `chunk_id`, `period_*` from the backend. Don't rename in the UI.
- "Reconciled" / "Not reconciled" — exactly these strings.
- "Apply & re-extract" / "Force finalize" — preserved from the
  existing UI.

### 8.4 Test discipline

- After every phase, run:
  ```
  pnpm tsc --noEmit
  pnpm biome check src/
  ```
  Both must pass before moving to the next phase.
- Unit tests are out of scope for this PRD — visual / E2E suffices
  for the redesign. The backend tests in P4 are required.

---

## 9 · Risk + rollback

| Risk                                          | Mitigation                                                          |
|-----------------------------------------------|---------------------------------------------------------------------|
| Backend SSE doesn't ship in time              | P5 can stand alone with a static timeline; revisit P4 later         |
| `astream_events` overhead too high            | Fall back to `astream(stream_mode="updates")` — coarser but cheaper |
| Existing CSP blocks Google Fonts              | Self-host woff2 in `public/fonts/`, switch `@import` → `@font-face` |
| `frontend/src/types.ts` schema drifts         | The TSX components import from `./types` — drift surfaces in tsc    |
| Biome flags inline `style={{…}}` usage        | Whitelisted; the existing repo already uses inline styles heavily   |

---

## 10 · Done definition

- Three views look like the kit in `ledger-ds/ui_kits/statement_analyzer/`.
- Live agent timeline updates within ~100 ms of backend state
  transitions.
- Review modal can apply corrections OR force-finalize, and the
  final ExtractResult round-trips correctly.
- All TypeScript / Biome checks pass.
- One unhandled-promise-rejection-free run of the Ixonia sample
  end-to-end in the browser.

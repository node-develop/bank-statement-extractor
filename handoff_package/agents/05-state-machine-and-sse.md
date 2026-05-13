# Agent prompt — Phase 5–6: State machine + SSE client

You are the `react-engineer` subagent. Phases 5 and 6 of
`PRD-redesign.md` §6 + §7. Do P5 first, smoke-test, then P6.

## Read first

1. `PRD-redesign.md` §6 and §7.
2. `frontend/src/App.tsx` (current — being replaced).
3. `frontend/src/api.ts` (current — being extended in P6).
4. `frontend/src/types.ts` and `frontend/src/types-progress.ts`.
5. The drop's `src/App.tsx`, `src/components/ProcessingView.tsx`,
   `src/components/ResultsView.tsx`, `src/components/ReviewModal.tsx`.

## Phase 5: drop the state-machine

1. **Copy** from drop:

   ```
   src/components/ProcessingView.tsx           → NEW
   src/components/ResultsView.tsx              → NEW
   src/components/ReviewModal.tsx              → REPLACE existing
   src/App.tsx                                 → REPLACE existing
   ```

2. **Delete** `frontend/src/components/UploadForm.tsx` (replaced by
   `UploadView.tsx` dropped in Phase 3).

3. **Verify** the imports in the new `App.tsx` resolve:
   - `./types` for `ExtractResult`, `PeriodResult`
   - `./types-progress` for `ExtractionProgress`, `ProgressCallback`
   - `./lib/agentSteps` for `AGENT_STEPS`
   - `./api` for `extractStatement`, `submitReview`, `ApiError`
   - `./components/*` for the views

4. **Run**:
   ```
   pnpm tsc --noEmit
   pnpm biome check src/
   pnpm dev
   ```

5. **Manual smoke**: upload the Ixonia sample. The processing view
   shows the timeline (inert because no SSE yet — fine). On
   completion, the results view renders with all 10 periods. Click
   "Open review" → the modal opens. Click "Force finalize" — submits
   via `submitReview` and the result updates.

## Phase 6: add SSE client

Extend `frontend/src/api.ts`:

```ts
// Add this signature
export async function extractStatement(
  pdfFile: File,
  ocrFile?: File,
  onProgress?: ProgressCallback,
): Promise<ExtractResult> { … }
```

Implementation:

1. Build the multipart `FormData` as today.
2. Start the `fetch("/extract", { method: "POST", body, signal })`.
3. The backend response sets header `X-Thread-Id` before flushing
   the body. Use `fetch` + `response.headers.get("X-Thread-Id")` —
   note: with `fetch` the headers arrive when the response promise
   resolves; you may need a short-lived `fetch(..., { signal })` and
   `EventSource` started immediately after.
4. Open `new EventSource("/extract/stream/" + threadId)`.
5. On each `message` event: parse JSON, fold into an
   `ExtractionProgress` accumulator, call `onProgress(snapshot)`.
6. On `{"kind":"done"}` event: close the EventSource.
7. `await` the original fetch, parse JSON, return `ExtractResult`.

Aggregation logic — pseudo:

```ts
const acc: ExtractionProgress = emptyProgress();
const periodOrder: PeriodChip[] = [];

function fold(ev) {
  if (ev.kind === "step") {
    const i = acc.steps.findIndex((s) => s.step_id === ev.step_id);
    acc.steps[i] = { ...acc.steps[i], state: ev.state, progress: ev.progress, elapsed_ms: ev.elapsed_ms, fanout: ev.fanout };
    if (ev.state === "running") acc.active_step = ev.step_id;
  } else if (ev.kind === "cost") {
    acc.cumulative_cost_usd = ev.cumulative_cost_usd;
  } else if (ev.kind === "period") {
    acc.period_states[ev.chunk_id] = ev.state;
    if (!periodOrder.find((p) => p.id === ev.chunk_id)) {
      periodOrder.push({ id: ev.chunk_id, month: "Unknown", last4: "" });
      // month/last4 backfilled when the final ExtractResult arrives
    }
  }
}
```

Wire `periodOrder` through `App.tsx` → `ProcessingView.periods=`.

## Acceptance criteria

**Phase 5:**
- `pnpm tsc --noEmit` clean.
- `pnpm biome check src/` clean.
- Upload sample → processing view → results view, end-to-end with
  no console errors.
- Review modal: apply corrections and force-finalize paths both
  reach the backend and update the displayed result.

**Phase 6:**
- During an active extract, agent timeline lanes light up in order
  matching the backend events.
- Cost ticker counts up live (verify with two extracts: small +
  Ixonia sample).
- "Cancel" closes the EventSource AND aborts the underlying fetch
  (verify in Network tab).
- If the EventSource errors / 404s, the UI falls back to a static
  spinner state — does NOT crash the processing view.

## Do NOT

- Do NOT use a global state library (Redux, Zustand, jotai). Local
  `useState` in App.tsx is sufficient.
- Do NOT poll. SSE only. If SSE fails, log + fall back to "no live
  progress" — never poll.
- Do NOT mutate the `ExtractionProgress` accumulator in place
  inside `fold` — React state requires a new object per `setState`
  call. The pseudo-code above is illustrative; use a reducer or
  spread updates.

## Report back

`done`, `verified`, `left_todo`, `files_touched`. Include the
Network tab waterfall screenshot for one full Ixonia extract.

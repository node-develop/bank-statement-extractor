# Bank Statement Extractor — frontend redesign drop

This package is everything needed to land the **Bank Statement
Extractor** design system into your existing
`bank-statement-analizer/frontend/` codebase. Drop the files in
under `frontend/`, run the migration prompts against your subagents
(or do it by hand following `PRD-redesign.md`), and you end up with:

- Purple-accent design system (tokens, type, components).
- Live agent timeline that animates while the LangGraph pipeline
  runs (Server-Sent Events from the backend).
- Three-phase state machine UI: upload → processing → results,
  with a review modal as overlay.

## Package contents

```
handoff_package/
├── README.md                   ← you are here
├── PRD-redesign.md             ← phased implementation plan
├── agents/
│   ├── 01-foundation.md        ← Phase 1: tokens, fonts, assets
│   ├── 02-primitives.md        ← Phase 2: icons, ui primitives, types
│   ├── 03-stateless.md         ← Phase 3: stateless components
│   ├── 04-backend-streaming.md ← Phase 4: SSE endpoint (Python)
│   └── 05-state-machine-and-sse.md ← Phases 5+6: App.tsx + SSE client
└── frontend/                   ← drop these into frontend/
    ├── public/
    │   ├── logo.svg
    │   ├── mark.svg
    │   └── wordmark-short.svg
    └── src/
        ├── App.tsx             ← replaces existing
        ├── types-progress.ts   ← new types (merge into types.ts, or keep)
        ├── lib/
        │   └── agentSteps.ts
        ├── styles/
        │   ├── tokens.css      ← CSS custom properties (single source of truth)
        │   └── components.css  ← layered component classes
        └── components/
            ├── Header.tsx
            ├── UploadView.tsx
            ├── AgentTimeline.tsx
            ├── PeriodChipsBar.tsx
            ├── ProcessingView.tsx
            ├── PeriodCard.tsx      ← replaces existing
            ├── TransactionsTable.tsx
            ├── JSONViewer.tsx
            ├── ReviewModal.tsx     ← replaces existing
            ├── ResultsView.tsx
            ├── icons/
            │   └── index.tsx
            └── ui/
                ├── Button.tsx
                ├── Chip.tsx
                └── SectionLabel.tsx
```

## How to use

### Option A — drive it with agents

If you're using Claude Code / Cursor / similar with subagent
routing:

1. Place this entire `handoff_package/` directory at the repo root
   (alongside `frontend/`, `src/`, `docs/`, etc.).
2. Open `PRD-redesign.md` and skim §0–§1 for context.
3. Hand each phase to the right subagent:

   ```
   /task react-engineer  agents/01-foundation.md
   /task react-engineer  agents/02-primitives.md
   /task react-engineer  agents/03-stateless.md
   /task fastapi-engineer agents/04-backend-streaming.md
   /task react-engineer  agents/05-state-machine-and-sse.md
   ```

   Phases 4 and 5 can run in parallel (different files); the rest
   are sequential.

4. After each phase, run the acceptance-criteria block from
   `PRD-redesign.md` for that phase. Don't proceed unless they pass.

### Option B — manual migration

Skim `PRD-redesign.md` once end-to-end, then for each phase:

1. Copy the listed files from `handoff_package/frontend/` into
   `frontend/`.
2. Apply the edits described in the corresponding `agents/0N-*.md`.
3. Run the acceptance-criteria commands.

Total effort: ~14 hours focused work, mostly the backend SSE
piece (P4).

## Key contracts you build on (unchanged)

- `frontend/src/types.ts` — `ExtractResult`, `PeriodResult`,
  `Suspect`, `TransactionCorrection`, etc. The TSX components here
  import directly from `./types`. Don't redefine.
- Money fields are JSON-string decimals — never `parseFloat`. The
  `fmt$()` helper in `lib/agentSteps.ts` is the one allowed
  exception (UI-only).
- `frontend/src/api.ts` already has `extractStatement`,
  `submitReview`, `getReview`. Phase 6 adds an optional
  `onProgress` callback to `extractStatement`.

## What this drop does NOT include

- **No automated tests** for the frontend. The repo's tests live on
  the Python side; visual / e2e smoke is the bar for the UI redesign.
- **No CSP / self-hosted fonts.** Fonts load from Google CDN. If you
  have a strict CSP, move the woff2s into `frontend/public/fonts/`
  and swap the `@import` in `tokens.css` for `@font-face`.
- **No icon library.** Stroke SVGs are inlined (~17 icons). Add
  `lucide-react` if you grow past ~30.
- **No router.** `App.tsx` is a 3-state machine; no URL state.

## After landing

The single most useful follow-up is Phase 4 (backend SSE). Without
it, the agent timeline renders correctly but stays static for the
duration of the extract — you lose the entire "watch agents work"
value prop.

Once SSE is wired, consider these as separate small PRs (out of
scope here):

- Persist the user's last review-modal field edits to localStorage
  on tab close.
- A "compare to etalon" toggle on the results view that diffs each
  period's summary against the Ixonia golden numbers
  (`docs/ixonia-etalon.md`).
- A keyboard-driven "step through suspects" mode for batch review.

## Questions / drift

If a TS error pops up in the dropped files that you can't resolve,
it's almost certainly because:

- Your `types.ts` has drifted from the version this drop assumes.
  Diff against the current state of `types.ts` and adjust the prop
  types in the affected component.
- Your `api.ts` doesn't yet export `submitReview` / `getReview` /
  `ApiError`. That ships in PRD §5 of the existing
  `bank-statement-analizer/PRD.md` — make sure that's landed first.

Otherwise: open an issue and reference the line + the design
system project where this drop was generated.

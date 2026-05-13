# Agent prompt — Phase 3: Stateless components

You are the `react-engineer` subagent. Phase 3 of `PRD-redesign.md`
§4.

## Read first

1. `PRD-redesign.md` §4.
2. `frontend/src/components/PeriodCard.tsx` (old — being replaced).
3. `frontend/src/components/ReconciliationBanner.tsx` (old —
   being deleted; its role moves into PeriodCard).
4. `frontend/src/types.ts` — verify the prop types you'll use.
5. `bank-statement-analizer/docs/architecture.md` §domain
   invariants — to understand what suspect codes mean.

## Concrete edits

1. **Copy** these from the drop into the repo, REPLACING where
   noted:

   ```
   src/components/Header.tsx                   → NEW
   src/components/UploadView.tsx               → NEW
   src/components/AgentTimeline.tsx            → NEW
   src/components/PeriodChipsBar.tsx           → NEW
   src/components/TransactionsTable.tsx        → NEW
   src/components/PeriodCard.tsx               → REPLACE existing
   src/components/JSONViewer.tsx               → NEW
   ```

2. **Delete** `frontend/src/components/ReconciliationBanner.tsx`.

3. The new `PeriodCard.tsx` expects `period.transactions` to be a
   `Transaction[]`. If your fixture data has it under a different
   path, leave the component as-is and pass the array via the
   `transactions` prop.

4. **Manual visual test** — temporarily mount each component in
   `App.tsx` with fixture data:

   ```tsx
   // TEMP — revert after smoke check
   import fixture from "../../tests/fixtures/sample.json";
   return <PeriodCard period={fixture.periods[0]} initialOpen
                      transactions={fixture.periods[0].transactions} />;
   ```

   Confirm each component renders cleanly, then revert App.tsx.

5. **Run**:
   ```
   pnpm biome check src/components
   pnpm tsc --noEmit
   ```

## Acceptance criteria

- All 7 files exist; ReconciliationBanner deleted.
- `pnpm tsc --noEmit` passes.
- `pnpm biome check src/components` passes.
- Visual smoke: each of the 7 components renders without console
  warnings when mounted with fixture data.
- `PeriodCard` renders BOTH reconciled (no banner, green chip) and
  unreconciled (red chip + "Review" button) states correctly.
- `TransactionsTable` highlights a suspect row when
  `suspectsByRow` has an entry.
- `JSONViewer` "Copy JSON" writes to clipboard (verify via
  `navigator.clipboard.readText()` in DevTools).

## Do NOT

- Do NOT change the className strings — they must match the CSS
  classes in `src/styles/components.css`.
- Do NOT introduce React state in these components beyond what the
  drop already has (open/closed in `PeriodCard`, copied flash in
  `JSONViewer`, dragging + file selection in `UploadView`).
- Do NOT add a router — App.tsx state machine handles navigation.

## Report back

`done`, `verified`, `left_todo`, `files_touched`.

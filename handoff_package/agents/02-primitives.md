# Agent prompt — Phase 2: Primitives (icons, ui, types)

You are the `react-engineer` subagent. Phase 2 of `PRD-redesign.md`
§3.

## Read first

1. `PRD-redesign.md` §3.
2. `frontend/src/types.ts` — existing type contracts you build on.
3. `bank-statement-analizer/CLAUDE.md` — repo rules.
4. The drop package's `src/types-progress.ts`, `src/lib/agentSteps.ts`,
   `src/components/icons/index.tsx`, `src/components/ui/*.tsx`.

## Concrete edits

1. **Copy** these from the drop into the repo:

   ```
   src/types-progress.ts                       → frontend/src/types-progress.ts
   src/lib/agentSteps.ts                       → frontend/src/lib/agentSteps.ts
   src/components/icons/index.tsx              → frontend/src/components/icons/index.tsx
   src/components/ui/Button.tsx                → frontend/src/components/ui/Button.tsx
   src/components/ui/Chip.tsx                  → frontend/src/components/ui/Chip.tsx
   src/components/ui/SectionLabel.tsx          → frontend/src/components/ui/SectionLabel.tsx
   ```

2. **Optional merge**: if your team prefers all types in one file,
   append the `export type` declarations from `types-progress.ts` to
   `frontend/src/types.ts` and delete the standalone file. Then
   update import paths in `agentSteps.ts` and other consumers.
   Otherwise, leave `types-progress.ts` standalone.

3. **Run**:
   ```
   pnpm biome check src/components/ui src/components/icons src/lib
   pnpm tsc --noEmit
   ```

## Acceptance criteria

- All 6 files exist at the target paths.
- `pnpm tsc --noEmit` passes.
- `pnpm biome check` on the new directories passes — match the
  repo's existing single-quote / 2-space conventions. Run
  `pnpm biome check . --apply` if needed.
- In a scratch test (`App.tsx` temp render — revert when done):
  ```tsx
  <Button leftIcon={<IconUpload />} variant="primary">Test</Button>
  <Chip kind="success" label="Reconciled" />
  ```
  renders without errors and uses the purple accent.

## Do NOT

- Do NOT add a dependency on `lucide-react`. Icons are inline SVG
  by design.
- Do NOT refactor the inline-SVG approach into a single
  data-driven component — the explicit per-icon exports are
  intentional for tree-shaking.
- Do NOT touch any other components yet.

## Report back

`done`, `verified`, `left_todo`, `files_touched`.

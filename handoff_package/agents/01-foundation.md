# Agent prompt — Phase 1: Foundation

You are the `react-engineer` subagent. Your task is Phase 1 of the
frontend redesign described in `PRD-redesign.md` §2.

## Read first (in order)

1. `PRD-redesign.md` §0–§2 (overview + this phase's spec).
2. `CLAUDE.md` (top-level repo rules — 12 rules, you must follow).
3. `frontend/index.html` and `frontend/src/main.tsx` (current
   entrypoint).
4. `frontend/src/index.css` (current — you will gut this).
5. `frontend/package.json` (confirm React 19, Vite, Biome versions
   in use).

## What's in the drop you're working from

`handoff_package/frontend/` contains the new files. For Phase 1
specifically:

```
src/styles/tokens.css        ← copy to frontend/src/styles/tokens.css
src/styles/components.css    ← copy to frontend/src/styles/components.css
public/logo.svg              ← copy to frontend/public/logo.svg
public/mark.svg              ← copy to frontend/public/mark.svg
public/wordmark-short.svg    ← copy to frontend/public/wordmark-short.svg
```

`components.css` references `tokens.css` via `@import "./tokens.css"` —
do not change that path.

## Concrete edits

1. **Copy** the 5 files above into the repo at the paths shown.
2. **Edit** `frontend/index.html`. Inside `<head>`, after the
   `<meta>` and `<title>` tags, add:

   ```html
   <link rel="preconnect" href="https://fonts.googleapis.com" />
   <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
   <link
     href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
     rel="stylesheet"
   />
   ```

3. **Edit** `frontend/src/main.tsx`. Add these imports **before**
   `import "./index.css";`:

   ```ts
   import "./styles/tokens.css";
   import "./styles/components.css";
   ```

4. **Edit** `frontend/src/index.css`. Replace the entire contents
   with a single line comment:
   ```css
   /* Reserved. Token + component styles live in src/styles/. */
   ```

5. **Run**:
   ```
   pnpm install
   pnpm biome check src/styles/
   pnpm tsc --noEmit
   pnpm dev
   ```
   Open the dev server. The page still uses the OLD App.tsx
   visuals — that's expected; this phase is foundation only. Confirm
   no console errors.

## Acceptance criteria

- All 5 files exist at the target paths.
- `index.html` has the Google Fonts `<link>`.
- `main.tsx` imports both new CSS modules before `index.css`.
- `pnpm tsc --noEmit` passes.
- `pnpm biome check src/styles/` passes (CSS files use Biome's CSS
  formatter if available, otherwise just left alone).
- In DevTools on the running dev server, `getComputedStyle(document.documentElement).getPropertyValue('--accent')` returns ` #5B33F0` (with a leading space).
- `/logo.svg` resolves and renders the lockup.

## Do NOT

- Do NOT touch `frontend/src/App.tsx` or any component yet. Phase 5
  handles that.
- Do NOT delete `index.css` — gut its contents but keep the file
  reference, or remove the import. Either is fine.
- Do NOT modify `tokens.css` or `components.css` contents. They're
  treated as vendored from the design system.

## Report back

A structured summary with: `done`, `verified` (the 5 criteria above),
`left_todo` (always `[]` if criteria pass), `files_touched`.

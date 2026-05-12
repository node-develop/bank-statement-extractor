---
name: react-upload-form-vite
description: Minimal Vite + React 19 + TS frontend with a single file-upload form, a JSON viewer, and a reconciliation banner. Use when scaffolding or modifying `frontend/`. Do NOT introduce routing, state, or UI libraries.
---

# Frontend: Vite + React + TS

## Layout

- `frontend/package.json` — react@19, react-dom@19, vite@5, typescript@5, @biomejs/biome.
- `frontend/vite.config.ts` — standard Vite React plugin.
- `frontend/tsconfig.json` — strict, `"jsx": "react-jsx"`.
- `frontend/biome.json` — formatter on, linter on, recommended rules.
- `frontend/index.html` — single `<div id="root"></div>`.
- `frontend/src/main.tsx` — `createRoot(...).render(<App />)`.
- `frontend/src/App.tsx` — the form. Hooks: `useState<File | null>`,
  `useState<ExtractResult | null>`, `useState<string | null>` (error).
- `frontend/src/api.ts` — `extract(file)` builds FormData, POSTs to
  `${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}/extract`.
- `frontend/src/types.ts` — `ExtractResult`, `Account`, `Summary`,
  `Transaction`, `Reconciliation`. Mirror the pydantic models exactly.

## Reconciliation banner

```tsx
{result?.reconciliation && !result.reconciliation.reconciled && (
  <div role="alert" style={{background: "#fee", padding: 12, border: "1px solid #d33"}}>
    <strong>Not reconciled.</strong> Delta: {result.reconciliation.delta}
    <ul>
      {result.reconciliation.notes.slice(0, 3).map((n, i) => <li key={i}>{n}</li>)}
    </ul>
  </div>
)}
```

## Rules

1. One component. If `App.tsx` exceeds 200 lines, split into `UploadForm`
   and `ResultViewer` — no further than that.
2. No `axios`. `fetch` is enough.
3. No `react-router`. We have one page.
4. Show progress as a simple `disabled` button + "Extracting…" text. No
   spinners.
5. Show the raw JSON in a `<pre>` block, monospace, scrollable.

## Anti-patterns

- Reaching for `react-query` for a single endpoint.
- Building a multi-step wizard for a one-shot upload.
- Adding Tailwind / shadcn / MUI — overkill for this scope.

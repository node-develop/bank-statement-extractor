# Pre-commit checklist

Run these before any commit. Hooks under `.claude/hooks/` automate most of
them on edit, but the final check is on the human.

1. `uv run ruff check .` — must be clean.
2. `uv run ruff format --check .` — must be clean.
3. `uv run mypy src` — must be clean (strict mode).
4. `uv run pytest -q` — must pass.
5. `uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf`
   — must reconcile for all 10 Ixonia periods. Any regression blocks the
   commit.
6. Frontend (if touched): `cd frontend && pnpm biome check . && pnpm tsc --noEmit`.
7. Commit message: imperative, ≤ 72 chars subject, body explains *why*.
8. **Never** commit anything under `Task/`, `.env*`, `*.key`, `*.pem`,
   `graph.sqlite`, `traces/`, `frontend/dist/`.

# bank-statement-analizer

Agent service that ingests a bank-statement PDF (with optional OCR text)
and returns structured `{account, summary, transactions}` JSON. Built on
LangGraph + LangChain + LangSmith, served by FastAPI, with a small
Vite + React + TypeScript form on top. Deployed via Dokploy 0.29.

> **Status:** scaffolding only. The behavioral contract, agent team,
> skills, hooks, and infra are wired. The graph nodes themselves are
> empty stubs — fill them in subsequent Claude Code sessions, driven by
> the agents in `.claude/agents/` and the skills in `.claude/skills/`.

## Quick start

```bash
# Prereqs: uv >= 0.4, Node 22 + pnpm, Docker
uv sync --extra dev

# Env (copy .env.example once created; do NOT commit .env)
export ANTHROPIC_API_KEY=sk-ant-...
export LANGSMITH_API_KEY=ls__...

# Run API
uv run uvicorn src.api.main:app --reload

# Run frontend
cd frontend && pnpm install && pnpm dev

# Eval on the sample
uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf
```

## Architecture

See `docs/architecture.md` (graph topology, state shape, error model).
See `docs/agent-team.md` (RACI for subagents).
See `docs/ixonia-etalon.md` (golden numbers for the Ixonia sample).

## Claude Code stack

This repo is wired for Claude Code per [artka.dev's Claude Code Guide](https://artka.dev/en/courses/claude-code-guide)
and the [12-rule CLAUDE.md template](https://artka.dev/en/blog/claude-md-12-rules/):

- `CLAUDE.md` — behavioral contract (12 rules), stack, layout, commands.
- `.claude/agents/` — 9 subagents: `langgraph-engineer`, `parser-architect`,
  `reconciler-engineer`, `fastapi-engineer`, `react-engineer`, `evaluator`,
  `dokploy-deployer`, `prompt-tuner`, `critic`.
- `.claude/skills/` — 11 SKILL.md packs covering domain, stack, deploy, MCP.
- `.claude/hooks/` — bash hooks for write protection, bash guard, format
  on write, session-start context, token-budget reminders, stop-checkpoint.
- `.claude/settings.json` — hook bindings, permissions, model defaults.
- `.mcp.json` — `context7` (live docs) + `git-nexus` (structured git).

## MCP + plugins to install

These are project-level dependencies; install once per machine:

```bash
# MCP servers — used by .mcp.json
# (no global install needed; npx fetches on first use)

# Claude Code plugins
/plugin install obra/superpowers   # superpowers skill pack
```

Set the corresponding env vars (e.g. `CONTEXT7_API_KEY`) before starting
the session.

## Deploy

```bash
docker compose -f infra/docker-compose.yml up --build
```

For Dokploy 0.29: point a new application at this repo with build type
`dockerfile`, path `infra/Dockerfile`. Manifest is in `infra/dokploy.json`.

## Test task

Original brief: `Task/task.md`. Sample data: `Task/Binder2_Redacted.pdf`
and `Task/ixonia_binder2_ocr.txt`. **Treat `Task/` as read-only.**

## License

MIT.

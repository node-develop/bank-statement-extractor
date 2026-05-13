# bank-statement-analizer

Agent service that ingests a bank statement (PDF + optional OCR text) and returns
account / per-period summary / line-item transactions as structured JSON. Built
on LangGraph + LangChain + LangSmith. FastAPI exposes `/extract`, a tiny
Vite + React + TS form drives the UI. Deployed via Dokploy 0.29.

The full task brief lives in `Task/task.md` — that folder is read-only, treat
its contents as a contract.

## Behavioral contract (12 rules)

These are imperatives, not wishes. Each rule prevents a specific failure mode
we have already paid for. They override anything below.

1. **Think before coding.** State assumptions out loud. If the bank layout is
   unclear from the OCR — ask, don't guess. Push back when there's a simpler way.
2. **Simplicity first.** Minimum code that reconciles on Ixonia. No speculative
   abstractions. One extra layer of "future flexibility" eats the budget.
3. **Surgical changes.** Touch only what's needed. Don't refactor neighboring
   nodes when adding a new extractor. Don't reformat code you weren't asked about.
4. **Goal-driven.** Success = summary fields exact-match the etalon and
   `beginning + Σdeposits − Σwithdrawals = ending` (within ε=$0.01) on Ixonia
   and on ≥2 unseen statements. That is the contract. Iterate against it.
5. **Use the model only for judgment.** Account numbers, dates, amounts come
   from the document — through extraction with verbatim grounding, not vibes.
   Routing/retry/reconciliation are deterministic Python, not LLM calls.
6. **Token budgets are not advisory.** 4k per task, 30k per session. If a node
   is about to dump the whole 99-page OCR into a prompt — chunk it. Per-statement
   end-to-end target ≤ 200k tokens including subagent calls. Stop and recap if
   approaching the boundary.
7. **Surface conflicts, don't average them.** If pdfplumber rows and OCR rows
   disagree — pick one (PDF first, OCR fallback), explain why, flag the rest
   for review. Never silently merge incompatible sources.
8. **Read before you write.** Before adding a new extractor / node / prompt,
   read `src/graph/state.py`, the existing nodes in `src/nodes/`, and the
   etalon in `docs/ixonia-etalon.md`. Use `mcp-context7` to pull current
   LangGraph / LangChain docs instead of guessing API surface.
9. **Tests verify intent.** An eval that says "structure is valid" is not a
   test. Tests assert reconciled totals, exact transaction counts, and that
   reconciliation flags a known-broken statement. Snapshot tests with no
   business assertions fail this rule.
10. **Checkpoint after every significant step.** Use LangGraph's checkpointer.
    After each multi-file edit — summarize done / verified / left. If you lose
    track, stop and recap; don't keep building on broken state.
11. **Match conventions.** Python: ruff + ruff format + mypy strict. Frontend:
    biome. snake_case Python, camelCase TS, kebab-case files. Imperative git
    commits. Decimal for money, never float. Don't introduce a new pattern just
    because you like it better.
12. **Fail loud.** Reconciliation mismatch is not a warning, it's a `reconciled:
    false` in the response with a `delta` and `notes[]`. OCR confidence below
    threshold raises. A skipped page is an error, not a silent gap. Default to
    surfacing uncertainty, not concealing it.

## Stack

- Python ≥ 3.14 (user-pinned; see note in `pyproject.toml`)
- LangGraph (state graph), LangChain (LLM I/O), LangSmith (tracing/evals)
- Anthropic Claude only: Sonnet 4.6 for extraction, Haiku 4.5 for routing/critic
- FastAPI + uvicorn for HTTP
- pdfplumber (primary) + pypdf (fallback) for PDF; OCR text is consumed as-is
- Frontend: Vite + React + TypeScript + biome
- Deploy: Dokploy 0.29 (docker-compose based)
- Package manager: `uv` (uv.lock is the source of truth)

## Repository layout

```
bank-statement-analizer/
├── CLAUDE.md                  # this file
├── .claude/
│   ├── settings.json          # hooks + permissions + model defaults
│   ├── agents/                # subagent definitions (planning, extraction, critique)
│   ├── skills/                # SKILL.md packs for the domain & stack
│   └── hooks/                 # bash scripts wired in settings.json
├── .mcp.json                  # mcp-context7, mcp-git-nexus
├── docs/
│   ├── architecture.md        # graph topology, node responsibilities
│   ├── agent-team.md          # which subagent for which task
│   ├── ixonia-etalon.md       # golden numbers from Task/task.md
│   └── prompts.md             # prompt engineering log
├── src/
│   ├── graph/                 # state.py, builder.py, checkpointer.py
│   ├── nodes/                 # preprocess, classify, extract_*, reconcile, finalize
│   ├── api/                   # FastAPI routers
│   ├── models/                # pydantic schemas (Statement, Transaction, Summary)
│   ├── prompts/               # versioned prompt templates
│   └── evals/                 # LangSmith dataset + scorers
├── frontend/                  # Vite + React + TS, one-file upload form
├── infra/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── dokploy.json
├── Task/                      # READ-ONLY: source brief + sample data
├── pyproject.toml
└── README.md
```

## Commands

- `uv sync` — install deps
- `uv run uvicorn src.api.main:app --reload` — local API on :8000
- `uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf` — eval
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src` — lint
- `uv run pytest -q` — tests
- `cd frontend && pnpm dev` — frontend on :5173

## Conventions

- **Money:** `decimal.Decimal`, never float. Comparison tolerance ε = `Decimal("0.01")`.
- **Dates:** ISO 8601 strings in the wire schema; `datetime.date` inside Python.
- **Pydantic v2.** All graph state fields are pydantic models or TypedDict with
  explicit reducers (`Annotated[list, add]` etc.).
- **Prompts** live in `src/prompts/*.md`, loaded by name, versioned in git.
  Never inline >20 lines of prompt text in Python.
- **LangSmith:** every graph run sets `run_name = f"{bank}:{period}"`, tags
  `["extract", bank_slug]`, metadata `{statement_hash, statement_pages}`.
- **No bare `except`.** Catch specific exceptions; let real errors propagate.

## Prohibitions

- Do **not** edit anything under `Task/` — it's the reference contract.
- Do **not** hardcode bank-specific logic in Python. Bank specifics live in
  prompts and few-shot exemplars only. The code stays bank-agnostic.
- Do **not** use `print` for logging. Use the `logging` module configured in
  `src/api/logging.py` and LangSmith for run-scoped tracing.
- Do **not** commit `.env*`, `*.key`, `*.pem`, anything under `secrets/`.
- Do **not** add `requests` / `httpx` clients — Anthropic access goes through
  LangChain's `ChatAnthropic`; nothing else makes outbound calls.
- Do **not** introduce SQLAlchemy / ORM — this service is stateless apart from
  the LangGraph checkpointer (SQLite by default, Postgres via env).

## MCP usage

- **`mcp-context7`** — query for current docs of LangGraph, LangChain,
  LangSmith, FastAPI, pdfplumber, Pydantic v2 before assuming API surface
  (rule 8). Example: `mcp__context7__resolve-library-id` → `query-docs` on
  `langgraph state graph checkpointer`.
- **`mcp-git-nexus`** — use for git operations from agent loops (branch,
  stage, commit, diff review). Configured in `.mcp.json`.

## Subagents

Each agent is invocable as a subagent (`Task` tool). See `docs/agent-team.md`
for the full RACI matrix. Quick map:

- `parser-architect` — designs prompts for an unseen bank layout
- `langgraph-engineer` — graph topology, nodes, state, checkpointers
- `reconciler-engineer` — pure-Python reconciliation logic, decimal math
- `fastapi-engineer` — endpoint + multipart upload + streaming
- `react-engineer` — frontend form
- `evaluator` — runs `src/evals` on Ixonia + held-out samples
- `dokploy-deployer` — Dockerfile / compose / dokploy.json
- `prompt-tuner` — iterates on extraction prompts when accuracy degrades
- `critic` — independent review against the 12 rules

## Skills

Project-local skills under `.claude/skills/` cover: bank-statement domain,
LangGraph state design, LangSmith tracing, PDF text extraction strategy,
reconciliation math, FastAPI multipart upload, React+Vite upload form,
Dokploy 0.29 deploy, MCP usage (context7, git-nexus), Anthropic model
routing. Superpowers skill pack is installed globally; project skills extend it.

## Before any commit

@docs/precommit.md

## Sub-system details

@docs/architecture.md
@docs/agent-team.md
@docs/ixonia-etalon.md

## How to drive development

@docs/runbook.md

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **bank-statement-analizer** (1383 symbols, 2176 relationships, 24 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/bank-statement-analizer/context` | Codebase overview, check index freshness |
| `gitnexus://repo/bank-statement-analizer/clusters` | All functional areas |
| `gitnexus://repo/bank-statement-analizer/processes` | All execution flows |
| `gitnexus://repo/bank-statement-analizer/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

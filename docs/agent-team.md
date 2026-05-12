# Agent team

Subagents are invoked from the main session via the `Task` tool. Each one
has a focused system prompt and a tool allow-list in `.claude/agents/<name>.md`.

## RACI by task

| Task | Driver agent | Reviewer |
|---|---|---|
| Add a new bank layout prompt | `parser-architect` | `critic` |
| Implement / refactor a graph node | `langgraph-engineer` | `critic` |
| Touch reconciliation math | `reconciler-engineer` | `evaluator` |
| FastAPI endpoint / upload / streaming | `fastapi-engineer` | `critic` |
| React form / API client | `react-engineer` | `critic` |
| Run / interpret evals | `evaluator` | — |
| Dockerfile / docker-compose / Dokploy | `dokploy-deployer` | `critic` |
| Iterate on extraction prompts | `prompt-tuner` | `evaluator` |
| Independent design review | `critic` | — |

## Invocation rules

- Default model: each agent declares its own in frontmatter.
- Token budget per subagent call: 30k context. If a task needs more —
  split it.
- A subagent **never** edits files outside its declared `cwd_glob`. Hooks
  enforce this (see `.claude/hooks/pre-write-protect-task.sh` analog).
- A subagent **must** return a structured summary (`done`, `verified`,
  `left_todo`, `files_touched`). Free-form prose is rejected by `critic`.

## Concurrency

- `extract_*` extractors inside the graph run in parallel via LangGraph's
  `add_conditional_edges` with parallel branches — these are graph nodes,
  not subagents, no cross-context confusion.
- Subagents for code work run sequentially in the Claude Code session,
  except `langgraph-engineer` + `react-engineer` which never touch the
  same files and can run in parallel when called from the main thread.

## Anti-patterns

- Don't launch `critic` *during* an extraction iteration — only at the
  end of a code change. Mid-task self-review burns tokens with little gain.
- Don't let `prompt-tuner` edit Python code; only `src/prompts/*.md`.
- Don't let `evaluator` write production code; only `src/evals/*` and
  `docs/*` (eval reports).

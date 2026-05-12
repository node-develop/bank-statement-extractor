---
name: git-nexus-usage
description: How to use mcp-git-nexus from agent loops for staging, committing, branching, and reviewing diffs without dropping to raw shell. Use for any git operation inside Claude Code sessions. Do NOT use for github.com API calls (that's a separate MCP).
---

# Using mcp-git-nexus

## Why an MCP for git

The `Bash` tool can run `git`, but mcp-git-nexus gives structured outputs
(file lists, hunks, branch names) that the model can reason about without
re-parsing terminal noise.

## Typical flow

1. `git_nexus.status()` — see what changed.
2. `git_nexus.diff(staged: false)` — review unstaged changes before
   staging. This is the rule-8 "read before write" applied to git.
3. `git_nexus.add(paths)` — stage explicitly. Never `add .` from an agent
   — surface unintended files first.
4. `git_nexus.commit(message)` — imperative subject ≤ 72 chars, body
   explains *why*. The agent's `critic` reviews this before push.
5. `git_nexus.branch_create(name)` — for feature work, branch off main.

## Rules

1. **Never push from an agent.** Push is a human action.
2. **Never force-push.** Even as a human action — only via explicit user
   instruction.
3. **Pre-commit hook still runs.** mcp-git-nexus calls the same `git
   commit` underneath; our `.pre-commit-config.yaml` (if present) and the
   `.claude/hooks/stop-checkpoint.sh` still gate.
4. **Don't commit `Task/`, `.env*`, `*.key`, `graph.sqlite`, eval
   reports, `frontend/dist/`, `traces/`.** Listed in `.gitignore`.

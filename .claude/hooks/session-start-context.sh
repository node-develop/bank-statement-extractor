#!/usr/bin/env bash
# SessionStart: inject project-specific reminders into the system prefix.
# Stdout text is appended to the model's context.
set -euo pipefail

cat <<'CTX'
[bank-statement-analizer context]
- Etalon for Ixonia Apr 2025 (account 1664): deposits 81 / $1,214,254.05;
  withdrawals 111 / $1,302,201.16; begin $597,068.70; end $509,121.59.
- Reconciliation invariant: beginning + Σdeposits − Σwithdrawals = ending ± $0.01.
- Token budget reminder: ≤ 4k per task, ≤ 30k per session (CLAUDE.md rule 6).
- Task/ is READ-ONLY. mcp-context7 before assuming an API. Subagents in .claude/agents/.
CTX
exit 0

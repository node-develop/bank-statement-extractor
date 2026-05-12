#!/usr/bin/env bash
# PostToolUse: append a one-line audit entry to traces/ for cross-referencing with LangSmith.
set -euo pipefail
input="$(cat)"
ts="$(date -u +%FT%TZ)"
tool="$(echo "$input" | jq -r '.tool_name // empty')"
session="$(echo "$input" | jq -r '.session_id // "?"')"
[[ -z "$tool" ]] && exit 0

mkdir -p "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/traces"
echo "$ts session=$session tool=$tool" >> "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/traces/agent.log"
exit 0

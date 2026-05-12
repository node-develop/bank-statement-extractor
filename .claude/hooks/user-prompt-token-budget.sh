#!/usr/bin/env bash
# UserPromptSubmit: nudge the model when the cumulative session size crosses budgets.
# Uses a small counter file keyed by session id.
set -euo pipefail
input="$(cat)"
session_id="$(echo "$input" | jq -r '.session_id // "unknown"')"
counter_file="/tmp/claude-bsa-${session_id}.count"
count="$(cat "$counter_file" 2>/dev/null || echo 0)"
count=$((count + 1))
echo "$count" > "$counter_file"

if (( count == 20 )); then
  echo "BUDGET: 20 user turns this session. Time to recap (rule 10) and consider /clear." >&2
fi
if (( count == 40 )); then
  echo "BUDGET: 40 user turns. Strongly consider /clear and starting fresh with a summary." >&2
fi
exit 0

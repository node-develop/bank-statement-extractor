#!/usr/bin/env bash
# PreToolUse: matcher=Bash — sanity-check destructive commands.
set -euo pipefail
input="$(cat)"
cmd="$(echo "$input" | jq -r '.tool_input.command // empty')"
[[ -z "$cmd" ]] && exit 0

# Hard blocks
if echo "$cmd" | grep -qE '(rm -rf /|:\(\)\{[^}]*\};:|dd +if=/dev/zero|mkfs\.|drop database|git +push +-f|git +push +--force)'; then
  echo "BLOCKED: destructive or non-recoverable command: $cmd" >&2
  exit 2
fi

# Hard block: editing Task/ via shell
if echo "$cmd" | grep -qE '(>|>>|mv|cp|sed -i|tee|truncate).+(Task/|/Task/)'; then
  echo "BLOCKED: writing inside Task/ via shell. Task/ is read-only." >&2
  exit 2
fi

# Warn (not block) on prod-env runs
if echo "$cmd" | grep -q 'NODE_ENV=production\|ENV=prod\|DJANGO_SETTINGS_MODULE=prod'; then
  echo "WARN: command targets a production-like env: $cmd" >&2
fi
exit 0

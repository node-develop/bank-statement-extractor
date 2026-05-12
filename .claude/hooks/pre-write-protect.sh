#!/usr/bin/env bash
# PreToolUse: block edits to Task/, secrets, lockfiles we don't own.
# Stdin: JSON { tool_input.file_path | tool_input.path | tool_input.command }
# Exit 2 + stderr = block with reason (shown to the model).

set -euo pipefail
input="$(cat)"
path="$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')"
[[ -z "$path" ]] && exit 0

case "$path" in
  */Task/*|Task/*)
    echo "BLOCKED: Task/ is read-only. It is the test-task contract — never edit. (CLAUDE.md prohibitions)" >&2
    exit 2 ;;
  *.env|*.env.*|*/.env|*/.env.*)
    echo "BLOCKED: do not edit .env files; secrets go through Dokploy env mapping." >&2
    exit 2 ;;
  *.key|*.pem|*/secrets/*)
    echo "BLOCKED: secret material is never edited by an agent." >&2
    exit 2 ;;
  */graph.sqlite|*/uv.lock)
    echo "BLOCKED: $path is generated; regenerate via 'uv sync' or the LangGraph runtime." >&2
    exit 2 ;;
esac
exit 0

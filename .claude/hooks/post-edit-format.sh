#!/usr/bin/env bash
# PostToolUse: matcher=Edit|Write — auto-format Python with ruff, frontend with biome.
set -euo pipefail
input="$(cat)"
path="$(echo "$input" | jq -r '.tool_input.file_path // empty')"
[[ -z "$path" ]] && exit 0
[[ ! -f "$path" ]] && exit 0

case "$path" in
  *.py)
    command -v ruff >/dev/null && {
      ruff format "$path" 2>&1 || true
      ruff check --fix "$path" 2>&1 || true
    }
    ;;
  *.ts|*.tsx|*.js|*.jsx|*.json|*.md)
    # biome inside frontend/ subtree only — leave docs/*.md alone for human prose
    if [[ "$path" == */frontend/* ]]; then
      (cd "$(dirname "$path")" && command -v npx >/dev/null && npx --no-install biome format --write "$(basename "$path")" 2>&1 || true)
    fi
    ;;
esac
exit 0

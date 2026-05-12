#!/usr/bin/env bash
# Stop: lightweight git checkpoint if the working tree changed.
# Runs in background; never blocks session end.
set -euo pipefail
( cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0
  # Only on bank-statement-analizer
  case "$(basename "$PWD")" in
    bank-statement-analizer) ;;
    *) exit 0 ;;
  esac
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git add -A
    git commit -m "wip: claude checkpoint" --no-verify >/dev/null 2>&1 || true
  fi
) &
exit 0

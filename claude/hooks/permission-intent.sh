#!/usr/bin/env bash
set -euo pipefail

if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' 'permission intent unavailable: Node is missing' >&2
  exit 2
fi
if output="$(node "$HOME/.claude/policy/permission-hook.js")"; then
  if [[ -n "$output" ]]; then printf '%s\n' "$output"; fi
else
  printf '%s\n' 'permission intent unavailable: hook failed' >&2
  exit 2
fi

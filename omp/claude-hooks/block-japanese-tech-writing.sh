#!/bin/bash
# PreToolUse:Bash — block gh pr create when its Japanese technical prose fails the gate
set -euo pipefail

HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .command // ""' 2>/dev/null || echo "")

if ! printf '%s' "$COMMAND" | grep -qE '(^|&&|;|\|)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=\S*[[:space:]]+)*(gh|rtk[[:space:]]+gh)[[:space:]]+pr[[:space:]]+create\b'; then
  exit 0
fi

if REASON=$(python3 "$HOOK_DIR/../policy/japanese_tech_writing.py" check-command "$COMMAND" 2>&1); then
  exit 0
fi

jq -n --arg reason "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": ("BLOCKED: 日本語技術文書ゲートに違反しています。" + $reason)
  }
}'
exit 0

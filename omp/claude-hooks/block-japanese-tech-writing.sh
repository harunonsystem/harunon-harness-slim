#!/bin/bash
# PreToolUse:Bash — block gh pr create / edit when the Japanese technical prose of its body fails the gate
set -euo pipefail

HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .command // ""' 2>/dev/null || echo "")

if ! printf '%s' "$COMMAND" | grep -qE '\bgh\b'; then
  exit 0
fi

if REASON=$(python3 "$HOOK_DIR/../policy/japanese_tech_writing.py" check-command "$COMMAND" 2>&1); then
  exit 0
fi

jq -n --arg reason "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": ("BLOCKED: 日本語技術文書ゲートに違反しています。" + $reason + " PR本文を確定後、利用可能なら yomiyasu --domain business で最終推敲してください。未導入の場合は指摘された表現をその場で修正してから再実行してください。")
  }
}'
exit 0

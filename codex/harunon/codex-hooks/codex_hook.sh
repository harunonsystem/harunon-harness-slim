#!/bin/bash
# 起動失敗の非zero終了をCodexは許可として扱うため、必須guardの失敗をdeny応答に変える。
if command -v node >/dev/null 2>&1; then
  if node "${BASH_SOURCE[0]%/*}/codex_hook.mjs"; then
    exit 0
  fi
fi
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Core Workflow blocked: Node is unavailable or the Codex guard could not start. Restore Node in the runtime PATH before retrying."}}'

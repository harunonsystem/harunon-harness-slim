#!/bin/bash
# PostToolUse:Write|Edit — settings.json / CLAUDE.md / RTK.md / rules/*.md を編集したら
# 「セッションを切り直す」reminder を出す（キャッシュ破棄を1回に集約するため）。
# 1 セッションにつき 1 回だけ出す（stdin の session_id をキーにした flag file で抑制。
# TMPDIR はセッションを跨いで永続するため、固定名だと「マシンで 1 回」になってしまう）。
set -uo pipefail

INPUT=$(cat)
FILE_PATH="${FILE_PATH:-}"

# env で FILE_PATH を渡さない実行系（PostToolUse の env 展開に依存しない runtime）
# 向けに、stdin の tool_input.file_path をフォールバックとして解決する。
if [ -z "$FILE_PATH" ]; then
  FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
fi

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

if ! [[ "$FILE_PATH" =~ (packages/core/)?(settings\.json|CLAUDE\.md|RTK\.md|rules/.*\.md)$ ]]; then
  exit 0
fi

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
FLAG="${SESSION_RESTART_REMINDER_FLAG:-${TMPDIR:-/tmp}/claude-session-restart-reminder-${SESSION_ID:-$PPID}}"

if [ -f "$FLAG" ]; then
  exit 0
fi

mkdir -p "$(dirname "$FLAG")" 2>/dev/null || true
: > "$FLAG"

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "settings.json / CLAUDE.md / RTK.md / rules を変更したらセッションを切り直す（キャッシュ破棄を1回に集約する）"
  }
}'
exit 0

#!/bin/bash
# PreToolUse:Bash|Read|Task|Agent — 過去の失敗から学んだ注意点を additionalContext で
# 警告する。すべて exit 0 の注入のみで block しない（advisory-only hook）。
set -uo pipefail

INPUT=$(cat)

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null)

WARNINGS=()

case "$TOOL_NAME" in
  Task|Agent)
    if printf '%s' "$PROMPT" | command grep -qE 'git[[:space:]]+(commit|push)|gh[[:space:]]+pr[[:space:]]+(create|merge)'; then
      WARNINGS+=("handoff packet に git 操作を入れない。deny で必ず落ちる。git 操作はメインセッションがユーザー確認後に行う")
    fi
    ;;
esac

if [ "$TOOL_NAME" = "Bash" ]; then
  if printf '%s' "$COMMAND" | command grep -qF '/home/user/'; then
    WARNINGS+=("cloud セッション由来のパス。ローカルは ~ 配下")
  fi
  if printf '%s' "$COMMAND" | command grep -qE 'gh[[:space:]]+issue[[:space:]]+(create|edit|close|comment)'; then
    WARNINGS+=("issue は Linear が正。Linear MCP（save_issue 等）に読み替える")
  fi
  if printf '%s' "$COMMAND" | command grep -qE '(^|[[:space:]])rm([[:space:]]|$)' \
     && printf '%s' "$COMMAND" | command grep -qF 'codex-review-done'; then
    WARNINGS+=("review gate flag の削除はユーザー指示が必要")
  fi
fi

if [ "$TOOL_NAME" = "Read" ]; then
  if printf '%s' "$FILE_PATH" | command grep -qF '/home/user/'; then
    WARNINGS+=("cloud セッション由来のパス。ローカルは ~ 配下")
  fi
fi

if [ "${#WARNINGS[@]}" -eq 0 ]; then
  exit 0
fi

JOINED=$(IFS='｜'; echo "${WARNINGS[*]}")
jq -n --arg ctx "$JOINED" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":$ctx}}'
exit 0

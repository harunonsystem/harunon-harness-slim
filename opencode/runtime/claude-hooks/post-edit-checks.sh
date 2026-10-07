#!/usr/bin/env bash
# post-edit-checks.sh [<file>]
#
# write / edit 直後のファイル品質チェックを runtime 中立に 1 本へまとめたもの。
#   引数あり: codex plugin / opencode plugin / omp extension が path を渡して呼ぶ。
#             pi は post-edit-checks.ts が同じ 3 チェックを内蔵する。指摘は plain text で stdout。
#   引数なし: Claude Code の PostToolUse hook。path は stdin JSON の .tool_input.file_path
#             （Claude は $FILE_PATH 等の env を渡さない）。指摘は additionalContext JSON で返す。
#   .md          → 隣の fix_gfm_tables.py でテーブルを GFM に自動修正（出力なし）
#   .sh          → shellcheck -S warning の指摘
#   .json        → jq のパースエラー（整形はしない。任意 repo の JSON を書き換えると重複キーの
#                  消失や prettier 形式との衝突が起きる）。コメントを許す JSONC 系は対象外
# 指摘は「モデルが自己修正するための追記」なので常に exit 0（block しない）。
# チェッカー未インストール時は静かにスキップする。
set -u

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_REPORT_LINES=15

file="${1:-}"
claude_mode=0
if [ -z "$file" ]; then
  command -v jq >/dev/null 2>&1 || exit 0
  claude_mode=1
  file="$(jq -r '.tool_input.file_path // empty' 2>/dev/null)"
fi
[ -n "$file" ] && [ -f "$file" ] || exit 0

report() {
  # $1: 見出し, stdin: 本文（先頭 MAX_REPORT_LINES 行だけ）
  local body
  body="$(printf '%s:\n' "$1"; head -n "$MAX_REPORT_LINES")"
  if [ "$claude_mode" = 1 ]; then
    jq -n --arg ctx "$file: $body" \
      '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
  else
    printf '%s\n' "$body"
  fi
}

case "$file" in
  # コメントを許す JSONC。jq で検査すると正当なコメントを「invalid JSON」と報告し、
  # モデルにコメントを消させてしまう。
  *.jsonc|*/tsconfig*.json|*/jsconfig*.json|*/.vscode/*.json|*/devcontainer.json) ;;
  *.md)
    [ -f "$HOOK_DIR/fix_gfm_tables.py" ] || exit 0
    command -v python3 >/dev/null 2>&1 || exit 0
    python3 "$HOOK_DIR/fix_gfm_tables.py" "$file" >/dev/null 2>&1 || true
    ;;
  *.sh)
    command -v shellcheck >/dev/null 2>&1 || exit 0
    out="$(shellcheck -S warning -- "$file" 2>&1)" && exit 0
    printf '%s\n' "$out" | report shellcheck
    ;;
  *.json)
    command -v jq >/dev/null 2>&1 || exit 0
    out="$(jq . < "$file" 2>&1 >/dev/null)" && exit 0
    printf '%s\n' "$out" | report "invalid JSON"
    ;;
esac
exit 0

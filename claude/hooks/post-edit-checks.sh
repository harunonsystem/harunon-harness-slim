#!/usr/bin/env bash
# post-edit-checks.sh <file>
#
# write / edit 直後のファイル品質チェック（Claude Code の PostToolUse 相当）を
# runtime 中立に 1 本へまとめたもの。codex plugin / opencode plugin / omp extension が
# 同じ判定を得るために呼ぶ。pi は post-edit-checks.ts が同じ 3 チェックを内蔵する。
#   .md          → 隣の fix_gfm_tables.py でテーブルを GFM に自動修正（出力なし）
#   .sh          → shellcheck -S warning の指摘を stdout に出す
#   .json/.jsonc → jq のパースエラーを stdout に出す
# 指摘は「モデルが自己修正するための追記」なので常に exit 0（block しない）。
# チェッカー未インストール時は静かにスキップする。
set -u

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_REPORT_LINES=15

file="${1:-}"
[ -n "$file" ] && [ -f "$file" ] || exit 0

report() {
  # $1: 見出し, stdin: 本文（先頭 MAX_REPORT_LINES 行だけ）
  printf '%s:\n' "$1"
  head -n "$MAX_REPORT_LINES"
}

case "$file" in
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
  *.json|*.jsonc)
    command -v jq >/dev/null 2>&1 || exit 0
    out="$(jq . < "$file" 2>&1 >/dev/null)" && exit 0
    printf '%s\n' "$out" | report "invalid JSON"
    ;;
esac
exit 0

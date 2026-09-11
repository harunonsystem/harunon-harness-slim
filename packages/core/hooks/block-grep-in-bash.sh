#!/bin/bash
# Claude Code / Codex の Bash ツールで禁止コマンド使用をブロックする
set -euo pipefail

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

COMMAND=$(echo "$INPUT" | jq -r '.command // .tool_input.command // ""')

# FP-8: quote 内の文字列引数（例: echo "grep で検索して"）を誤検知しないよう、
# 危険コマンド判定と同じ正規化を通した $NORMALIZED で判定する。ただしこれは
# style guard であって安全ガードではないため、danger 側と違い perl 不在/失敗を
# fail-closed にはしない（正規化できなければ生の $COMMAND で判定を続ける）。
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/command-normalize.sh
source "$HOOK_DIR/lib/command-normalize.sh" 2>/dev/null || true
# 存在確認してから source する（`source 不在ファイル || true` は bash 3.2 の
# set -e 下では || true が効かず即 exit 1 で落ちる既知の癖があるため、
# unreadable のケースでは source 自体を呼ばずに避ける）。
if [ -r "$HOOK_DIR/lib/denial-log.sh" ]; then
  # shellcheck source=lib/denial-log.sh
  source "$HOOK_DIR/lib/denial-log.sh"
fi
if declare -f normalize_command_available >/dev/null 2>&1 && normalize_command_available; then
  NORMALIZED=$(normalize_command "$COMMAND") || NORMALIZED="$COMMAND"
else
  NORMALIZED="$COMMAND"
fi

if echo "$NORMALIZED" | command grep -qE '(^|\||&&|;)[[:space:]]*(e|f)?grep\b'; then
  echo "grepではなくrg（ripgrep）を使ってください。または専用のGrepツールを使ってください。" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-grep-in-bash" "grep-in-bash" "$COMMAND" || true
  exit 2
fi

if echo "$NORMALIZED" | command grep -qE '(^|\||&&|;)[[:space:]]*sed\b'; then
  echo "sedではなくEditツールまたはperlを使ってください。例: perl -pi -e 's/old/new/g' file.txt" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-grep-in-bash" "sed-in-bash" "$COMMAND" || true
  exit 2
fi

if echo "$NORMALIZED" | command grep -qE '(^|\||&&|;)[[:space:]]*awk\b'; then
  echo "awkではなくperlを使ってください。例: perl -lane 'print \$F[0]' file.txt" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-grep-in-bash" "awk-in-bash" "$COMMAND" || true
  exit 2
fi

exit 0

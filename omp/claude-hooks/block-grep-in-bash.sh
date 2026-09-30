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

# 止めるのは再帰 grep（rg の方が .gitignore を尊重し速い）と sed のインプレース編集
# （Edit の read-before-write を迂回する）だけ。ファイル単体やパイプ内の grep、sed -n、
# awk は読み取りなので通す。Claude Code の auto mode がこれらを Bash で使うよう指示して
# おり、全面禁止だと 30 日で約 660 回の deny → 再試行を生んでいた（cclens 2026-09-30）。
# 判定範囲は同じコマンドの引数まで（[^|;&]*）。パイプ先の `sort -r` を grep に帰属させない。
# ponytail: sed の `w file` コマンドや grep -d recurse は見ていない。実測で出たら足す。
# grep のオプション判定用に、パターン引数をオプションと取り違えない形へ落とす:
#   - `-e <pattern>` の引数（`grep -e '-r' f`）。正規化は '' を消して次の語を繰り上げる
#     ため（`-e '' -r` → `-e  -r`）、quote が残っている正規化前のコマンドで落とす
#   - `--` 以降（`grep -- -r f`）。オプション解析はそこで終わる
GREP_FLAGS=$(echo "$COMMAND" | command sed -E "s/(^|[[:space:]])-e[[:space:]]+('[^']*'|\"[^\"]*\"|[^[:space:]|;&]+)/\\1/g")
if declare -f normalize_command_available >/dev/null 2>&1 && normalize_command_available; then
  GREP_FLAGS=$(normalize_command "$GREP_FLAGS") || GREP_FLAGS="$NORMALIZED"
fi
GREP_FLAGS=$(echo "$GREP_FLAGS" | command sed -E 's/[[:space:]]--([[:space:]][^|;&]*)?$|[[:space:]]--[[:space:]][^|;&]*([|;&])/ \2/g')
if echo "$GREP_FLAGS" | command grep -qE '(^|\||&&|;)[[:space:]]*(e|f)?grep\b[^|;&]*[[:space:]](-[A-Za-z]*[rR]|--(dereference-)?recursive\b)'; then
  echo "再帰検索は grep -r ではなく rg（ripgrep）を使ってください。例: rg -n 'pattern' src" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-grep-in-bash" "grep-in-bash" "$COMMAND" || true
  exit 2
fi

if echo "$NORMALIZED" | command grep -qE '(^|\||&&|;)[[:space:]]*sed\b[^|;&]*[[:space:]](-[A-Za-z]*i|--in-place)'; then
  echo "sed -i ではなく Edit ツールまたは perl を使ってください。例: perl -pi -e 's/old/new/g' file.txt（読み取りの sed -n は使えます）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-grep-in-bash" "sed-in-bash" "$COMMAND" || true
  exit 2
fi

exit 0

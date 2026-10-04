#!/bin/bash
# UserPromptSubmit — プロンプトとして届いた 1 行の `! <cmd>` を hook 側で実行する。
#
# Claude Code 本体の bash モードが拾わなかった `!` 行は、そのままプロンプトとして
# Claude に届く。行頭に空白が混ざったコピペや、Claude の作業中に打って queue に
# 積まれた入力がこれに当たる。hook は `^[空白]*!` の 1 行プロンプトを `!` と同じ
# 意味論で実行し、結果を additionalContext で返す。本体の bash モードが実行した
# 入力は `!` を含むプロンプトとして hook に届かないので、二重には実行しない。
#
# 対象は「1 行だけ」「先頭が !（前に空白可）」のプロンプトに限定する。複数行や本文中の
# `!` は触らない（貼り付けたログを誤って実行しない）。JSON パース失敗や prompt
# 欠落時は exit 0 で素通り（fail-open）。
set -uo pipefail

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

if [ -z "$PROMPT" ]; then
  exit 0
fi

# 複数行は対象外（末尾の改行だけは許容）
if printf '%s' "$PROMPT" | perl -0 -ne 'exit(($_ =~ /\S\s*\n\s*\S/) ? 0 : 1)'; then
  exit 0
fi

# -CS で stdin/stdout を UTF-8 として扱い、全角スペース（U+3000）も行頭空白に含める
CMD=$(printf '%s' "$PROMPT" | perl -CS -0 -ne 'print $1 if /\A[ \t\x{3000}]*![ \t]*(.+?)\s*\z/')
if [ -z "$CMD" ]; then
  exit 0
fi

TIMEOUT_SECONDS="${BANG_COMMAND_TIMEOUT_SECONDS:-120}"
OUTPUT=$(perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" bash -lc "$CMD" 2>&1)
STATUS=$?

CONTEXT=$(printf 'プロンプトとして届いた `! %s` を hook が実行しました（exit=%s）。以下がその出力です。ユーザーに実行済みであることを伝え、この出力を前提に続けてください。\n\n%s' \
  "$CMD" "$STATUS" "$OUTPUT")

jq -n --arg ctx "$CONTEXT" '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'
exit 0

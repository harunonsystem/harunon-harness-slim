#!/bin/bash
# UserPromptSubmit — 行頭に空白が混ざった `! <cmd>` を hook 側で実行する。
#
# Claude Code の `!` プレフィックスは行頭に無いとコマンド扱いにならず、そのまま
# プロンプトとして Claude に届く。ターミナルや code block からコピペすると行頭に
# 空白が混ざりやすく、ユーザーが同じ 1 行を 3 回打ち直しても実行されない往復が
# 発生した（2026-08-29）。CLAUDE.md の出力ルール（code block に入れない）だけでは
# 防げないので、hook が `^[空白]+!` の 1 行プロンプトを検出したときは `!` と同じ
# 意味論でコマンドを実行し、結果を additionalContext で返す。
#
# 対象は「1 行だけ」「先頭が空白 + !」のプロンプトに限定する。複数行や本文中の
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
CMD=$(printf '%s' "$PROMPT" | perl -CS -0 -ne 'print $1 if /\A[ \t\x{3000}]+![ \t]*(.+?)\s*\z/')
if [ -z "$CMD" ]; then
  exit 0
fi

TIMEOUT_SECONDS="${BANG_COMMAND_TIMEOUT_SECONDS:-120}"
OUTPUT=$(perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" bash -lc "$CMD" 2>&1)
STATUS=$?

CONTEXT=$(printf '行頭に空白の付いた `! %s` を hook が実行しました（exit=%s）。以下がその出力です。ユーザーに実行済みであることを伝え、この出力を前提に続けてください。\n\n%s' \
  "$CMD" "$STATUS" "$OUTPUT")

jq -n --arg ctx "$CONTEXT" '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'
exit 0

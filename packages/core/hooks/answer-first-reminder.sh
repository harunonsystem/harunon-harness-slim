#!/bin/bash
# UserPromptSubmit — 疑問形のプロンプトを検出したら Answer-first を促す reminder を注入する。
#
# Response Mode: Answer-first（診断的な質問にはツール実行より先に本文で回答する運用）を、
# プロンプト送信時点で毎回思い出させるための非ブロッキング reminder。JSON パース失敗や
# prompt 欠落時は必ず exit 0 で素通りする（fail-open。プロンプトを誤って握りつぶさない）。
# slash command は明示的な指示なので対象外。
set -uo pipefail

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

if [ -z "$PROMPT" ]; then
  exit 0
fi

case "$PROMPT" in
  /*) exit 0 ;;
esac

LAST_LINE=$(printf '%s' "$PROMPT" | command grep -v '^[[:space:]]*$' | tail -n1)

IS_QUESTION=0
if printf '%s' "$LAST_LINE" | command grep -qE '(\?|？)[[:space:]]*$'; then
  IS_QUESTION=1
elif printf '%s' "$LAST_LINE" | command grep -qE '(です|ます|でしょう)か[[:space:]]*$'; then
  IS_QUESTION=1
elif printf '%s' "$LAST_LINE" | command grep -qE '(だっけ|かな)[[:space:]]*$'; then
  IS_QUESTION=1
fi

if [ "$IS_QUESTION" -eq 0 ]; then
  exit 0
fi

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"疑問形の発話: ツール実行や Edit/Write より先に、この発話への回答を本文で書く（Response Mode: Answer-first。編集は明示的な変更依頼が来てから）"}}'
exit 0

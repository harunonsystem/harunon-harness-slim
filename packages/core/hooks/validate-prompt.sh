#!/bin/bash
# UserPromptSubmit — プロンプト送信時点で破壊的操作の兆候をログ+警告する。
#
# PreToolUse 層のガードはコマンド化された後にしか割り込めない。ここは入力送信時点
# （コマンド化前）で割り込める公式イベントを使い、早期に気付けるようにする。
#
# 初期実装は block しない。誤検知でワークフローを止めないため、検出してもログ記録と
# additionalContext での警告のみ（非ブロッキング）。JSON パース失敗や prompt 欠落時は
# 必ず exit 0 で素通りする（fail-open。プロンプトを誤って握りつぶさない）。
set -uo pipefail

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

if [ -z "$PROMPT" ]; then
  exit 0
fi

MATCHED=""

if printf '%s' "$PROMPT" | command grep -qiE 'drop[[:space:]]+table'; then
  MATCHED="DROP TABLE"
elif printf '%s' "$PROMPT" | command grep -qE 'rm[[:space:]]+-rf[[:space:]]+/([[:space:]]|$)'; then
  MATCHED="rm -rf /"
elif printf '%s' "$PROMPT" | command grep -qiE '(本番|prod(uction)?)' && \
     printf '%s' "$PROMPT" | command grep -qiE '(drop|delete|truncate|rm[[:space:]]+-rf|reset[[:space:]]+--hard|force[[:space:]]+push)'; then
  MATCHED="本番環境への破壊的操作の疑い"
fi

if [ -z "$MATCHED" ]; then
  exit 0
fi

LOG_DIR="$HOME/.claude"
if mkdir -p "$LOG_DIR" 2>/dev/null; then
  LOG_FILE="$LOG_DIR/prompt-guard.log"
  TIMESTAMP=$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || date)
  PROMPT_HEAD=$(printf '%s' "$PROMPT" | cut -c1-200)
  printf '%s\t%s\t%s\n' "$TIMESTAMP" "$MATCHED" "$PROMPT_HEAD" >> "$LOG_FILE" 2>/dev/null
fi

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"⚠️ 破壊的操作の可能性: %s。実行前にユーザーに確認すること。"}}\n' "$MATCHED"
exit 0

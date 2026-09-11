#!/bin/bash
# UserPromptSubmit — 再発バグ・逐語要求・ダイアグラム要求のパターンを検出して
# reminder を注入する。JSON パース失敗や prompt 欠落時は fail-open（exit 0）。
set -uo pipefail

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

if [ -z "$PROMPT" ]; then
  exit 0
fi

WARNINGS=()

if printf '%s' "$PROMPT" | command grep -qE 'またこれ|また同じ|同じ(バグ|エラー)|前にも(見た|あった)|前に直した|再発'; then
  WARNINGS+=("表面修正 REJECT。/diagnosing-bugs を Phase 1 から起動する")
fi

if printf '%s' "$PROMPT" | command grep -qE 'raw ?で|生のまま|そのまま(出して|見せて|貼って)|逐語'; then
  WARNINGS+=("要約・解説を挟まずコピペ可能な逐語テキストで返す")
fi

if printf '%s' "$PROMPT" | command grep -qiE 'ダイアグラム|構成図|フローチャート|シーケンス図|diagram|mermaid|figjam'; then
  WARNINGS+=("形式（Mermaid/FigJam・縦横）が未指定なら確定してから生成する")
fi

if [ "${#WARNINGS[@]}" -eq 0 ]; then
  exit 0
fi

JOINED=$(IFS='｜'; echo "${WARNINGS[*]}")
jq -n --arg ctx "$JOINED" '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'
exit 0

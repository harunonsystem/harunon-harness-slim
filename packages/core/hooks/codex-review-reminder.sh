#!/bin/bash
# PostToolUse:Bash — lightweight reminder after git commit succeeds

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では Codex レビューのリマインドをしない（ADR-009）。
[ "$(rigor_profile)" = "casual" ] && exit 0

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only trigger on git commit commands
if ! echo "$CMD" | grep -qE '(^|&&|;|\|)\s*(git|rtk git)\s+commit\b'; then
  exit 0
fi

# Check stdout for signs of successful commit
# PostToolUse の入力スキーマは tool_response（tool_result ではない）
STDOUT=$(echo "$INPUT" | jq -r '.tool_response.stdout // empty')
if ! echo "$STDOUT" | grep -qiE '(file changed|files changed|insertion|deletion|create mode)'; then
  exit 0
fi

# commit 成功: difit-done flag は今回のサイクルで消費済みなので削除する
# （block-commit-without-difit.sh が次回 commit で古い flag を見て誤って
# 通してしまわないようにする）。
# advisory hook: 解決不能なら何もせず exit 0（何かを断定して書き込まない）。
review_gate_resolve_target_repo "$CMD" || exit 0
if git rev-parse --show-toplevel > /dev/null 2>&1; then
  rm -f "$(difit_done_flag)" 2>/dev/null || true
fi

# PostToolUse の出力スキーマは additionalContext（message は無効フィールド）
jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "REMINDER: コミット完了。PR作成前に `/codex:review` を実行してください（hookでブロックされます）。"
  }
}'

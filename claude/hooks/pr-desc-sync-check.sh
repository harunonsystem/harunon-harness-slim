#!/bin/bash
# PostToolUse:Bash — push成功時にPR descriptionと現在のdiffの乖離チェックを促す
# Works with both raw `git push` and rtk-rewritten `rtk git push` commands.
# deny はしない。additionalContext のみ（作業エージェントへの指示）。

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if ! echo "$CMD" | grep -qE '(^|&&|;|\|)\s*(git|rtk git)\s+push\b'; then
  exit 0
fi

# 中断・失敗時は何もしない（push が実際に成功した時だけ確認を促す）。
# set-codex-review-flag.sh と同じ防御方針: exitCode 優先、既知の失敗シグネチャで補完。
INTERRUPTED=$(echo "$INPUT" | jq -r '.tool_response.interrupted // false')
EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exitCode // .tool_response.exit_code // empty')
OUTPUT=$(echo "$INPUT" | jq -r '(.tool_response.stdout // "") + "\n" + (.tool_response.stderr // "")')

if [ "$INTERRUPTED" = "true" ]; then
  exit 0
fi
if [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ]; then
  exit 0
fi
if echo "$OUTPUT" | grep -qE '! \[rejected\]|error:|fatal:|failed to push'; then
  exit 0
fi

# hook は Claude Code の CWD で実行される。CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# advisory hook: 解決不能なら何もせず exit 0。
review_gate_resolve_target_repo "$CMD" || exit 0

git rev-parse --show-toplevel > /dev/null 2>&1 || exit 0

# casual profile では PR description 同期チェックの促しをしない（ADR-009）。
# 解決済みの対象 repo で判定する（session cwd 基準だと対象とズレる）。
[ "$(rigor_profile)" = "casual" ] && exit 0

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

# gh 呼び出しは5秒でタイムアウトする（hookを遅く/うるさくしない）。
# フォールバック順は check-plan-model.sh と同じ: gtimeout → perl alarm → タイムアウトなし。
PR_JSON=""
if command -v gtimeout &>/dev/null; then
  PR_JSON=$(gtimeout 5 gh pr view "$BRANCH" --json number,body 2>/dev/null) || true
elif command -v perl &>/dev/null; then
  PR_JSON=$(perl -e 'alarm 5; exec @ARGV' gh pr view "$BRANCH" --json number,body 2>/dev/null) || true
else
  PR_JSON=$(gh pr view "$BRANCH" --json number,body 2>/dev/null) || true
fi

# gh 失敗・PR なしは silent に exit 0
[ -z "$PR_JSON" ] && exit 0

PR_NUMBER=$(echo "$PR_JSON" | jq -r '.number // empty')
[ -z "$PR_NUMBER" ] && exit 0

jq -n --arg pr "$PR_NUMBER" '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": ("push 済み。PR #" + $pr + " の description と現在の diff（base との merge-base 以降）を突き合わせ、乖離があれば更新案をユーザーに提示せよ。`gh pr edit` の自動実行は禁止、提示のみ。")
  }
}'

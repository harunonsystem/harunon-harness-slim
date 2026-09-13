#!/bin/bash
# PreToolUse:Bash — staged diff を機械分類し、difit 対象なら commit 前に /difit を要求する
# Works with both raw `git commit` and rtk-rewritten `rtk git commit` commands.

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/review-router.sh
source "$HOOK_DIR/lib/review-router.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"
# shellcheck source=lib/command-normalize.sh
source "$HOOK_DIR/lib/command-normalize.sh"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# commit 検出は共通の境界正規化（改行 / & / subshell / $( ) を起点として扱う）に乗せる。
# 前処理が失敗したら deny（difit 判定層の消失を allow に倒さない）。
if ! normalize_command_available; then
  echo "difit ゲートに必要な perl が見つかりません（安全側に倒してブロックします）" >&2
  exit 2
fi
origin_rc=0
command_origin_matches "$CMD" '(git|rtk git)[[:space:]]+commit([^A-Za-z0-9_-]|$)' || origin_rc=$?
case $origin_rc in
  0) ;;
  1) exit 0 ;;
  *)
    echo "difit ゲートのコマンド前処理に失敗しました（安全側に倒してブロックします）" >&2
    exit 2
    ;;
esac

# hook は Claude Code の CWD で実行されるため、CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# 解決不能なら対象 repo の difit 状態を確定できないため deny する。
if ! review_gate_resolve_target_repo "$CMD"; then
  jq -n --arg reason "$REVIEW_GATE_UNRESOLVABLE_REASON" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCKED: commit 対象 repo を確定できません（" + $reason + "）。対象 repo に cd してから実行してください。")
    }
  }'
  exit 0
fi

git rev-parse --show-toplevel > /dev/null 2>&1 || exit 0

# casual profile では difit ゲートを課さない（ADR-009）。解決済みの対象 repo で
# 判定する（session cwd 基準だと git -C / --cwd 経由の commit と flag キーの
# 基準 repo がズレる。判定順は load-bearing）。
[ "$(rigor_profile)" = "casual" ] && exit 0

DIFF_NAME_STATUS=$(git diff --cached --name-status 2>/dev/null || echo "")
NUMSTAT_TOTAL=$(git diff --cached --numstat 2>/dev/null | awk '{add+=$1; del+=$2} END {print add+del+0}')
ROUTE=$(printf '%s\n' "$DIFF_NAME_STATUS" | review_route "$NUMSTAT_TOTAL")

if [ "$ROUTE" != "difit" ]; then
  exit 0
fi

FLAG=$(difit_done_flag)
STALE_SUFFIX=""
if [ -f "$FLAG" ]; then
  # flag は set-difit-flag.sh / difit-skip.sh が書いた2行フィンガープリント
  # （staged diff ハッシュ / HEAD からの全diff ハッシュ）。commit 対象の
  # staged diff が現時点でそのどちらとも一致しなければ、difit 実行後に
  # diff が変わったとみなし deny する（flag の存在だけで通さない）。
  CURRENT_STAGED_HASH=$(git diff --cached 2>/dev/null | shasum | awk '{print $1}')
  if grep -qxF "$CURRENT_STAGED_HASH" "$FLAG"; then
    exit 0
  fi
  STALE_SUFFIX=" difit後にdiffが変わったため再レビューが必要です。"
fi

jq -n --arg stale "$STALE_SUFFIX" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": ("BLOCKED: 変更規模が大きい、またはUIコンポーネントを含むためdifitでのレビューが必要です。`/difit` を実行するか、`~/.claude/hooks/difit-skip.sh \"理由\"` でスキップしてください。" + $stale)
  }
}'

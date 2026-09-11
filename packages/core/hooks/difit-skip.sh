#!/bin/bash
# Manual skip for the difit gate.
# Usage: difit-skip "reason for skipping"
# Logs skip to ~/.claude/difit-skip.log for accountability.

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では difit ゲート自体を課さないため、skip 記録も不要。
[ "$(rigor_profile)" = "casual" ] && exit 0

REASON="${1:-}"

if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  echo "Usage: difit-skip \"理由\""
  echo "例: difit-skip \"軽微なリファクタで目視確認済み\""
  exit 1
fi

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
FLAG=$(difit_done_flag)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
LOG="${DIFIT_SKIP_LOG:-$HOME/.claude/difit-skip.log}"
mkdir -p "$(dirname "$LOG")"

# set-difit-flag.sh と同じ2行フィンガープリント形式で書く（skip は
# 「今のdiffの状態を承認した」ことになるため、同じ基準で紐付ける）。
{
  git diff --cached 2>/dev/null | shasum | awk '{print $1}'
  git diff HEAD 2>/dev/null | shasum | awk '{print $1}'
} > "$FLAG"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] SKIP repo=$GIT_ROOT branch=$BRANCH reason=\"$REASON\"" >> "$LOG"

echo "⚠ difitゲートをスキップしました"
echo "  理由: $REASON"
echo "  ログ: $LOG"

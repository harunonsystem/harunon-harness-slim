#!/bin/bash
# Reset the "codex review already done" flag to allow a 2nd review pass.
# Usage: codex-review-reset "reason for 2nd review"
# Only to be invoked after the user has explicitly approved a re-review.
# Logs reset to ~/.claude/codex-review-reset.log for accountability.
#
# KEY は lib/review-gate.sh（repo + branch）で算出する。旧実装（repo のみの
# 独自 shasum、~/.local/bin 直置き）は現行 flag 形式と KEY が一致せず
# 「Flag が存在しません」で空振りしていたため SSOT に移設して修正。

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では Codex レビューゲート自体を課さないため、reset も不要。
[ "$(rigor_profile)" = "casual" ] && exit 0

REASON="${1:-}"

if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  echo "Usage: codex-review-reset \"理由\""
  echo "例: codex-review-reset \"ユーザー指示により全件対応して再レビュー\""
  echo "例: codex-review-reset \"1回目が環境エラーでレビュー未実施のため再実行\""
  exit 1
fi

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
FLAG=$(codex_review_done_flag)
HEAD=$(git rev-parse HEAD 2>/dev/null)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
LOG="${CODEX_REVIEW_RESET_LOG:-$HOME/.claude/codex-review-reset.log}"
mkdir -p "$(dirname "$LOG")"

if [ ! -f "$FLAG" ]; then
  echo "ℹ Flag が存在しません（まだ 1 回目を実行していない or 既にリセット済み）"
  exit 0
fi

rm -f "$FLAG"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] RESET repo=$GIT_ROOT branch=$BRANCH head=${HEAD:0:7} reason=\"$REASON\"" >> "$LOG"

echo "♻ Codex レビュー flag をリセットしました（次回の /codex:review は通ります）"
echo "  理由: $REASON"
echo "  ログ: $LOG"

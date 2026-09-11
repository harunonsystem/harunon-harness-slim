#!/bin/bash
# Manual bypass for Codex review gate.
# Usage: codex-review-bypass "reason for skipping"
# Logs bypass to ~/.claude/codex-review-bypass.log for accountability.

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では Codex レビューゲート自体を課さないため、bypass 記録も不要。
[ "$(rigor_profile)" = "casual" ] && exit 0

REASON="${1:-}"

if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  echo "Usage: codex-review-bypass \"理由\""
  echo "例: codex-review-bypass \"ドキュメントのみの変更\""
  echo "例: codex-review-bypass \"Codex MCP障害中 - 緊急hotfix\""
  exit 1
fi

git rev-parse --show-toplevel > /dev/null 2>&1 || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
LOG="$HOME/.claude/codex-review-bypass.log"

codex_review_record_bypass "$REASON" "$LOG"

echo "⚠ Codexレビューゲートをバイパスしました"
echo "  理由: $REASON"
echo "  ログ: $LOG"

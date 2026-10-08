#!/bin/bash
# gh pr merge / close の承認フラグを立てる。
# Usage: approve-pr <PR番号> "理由" [merge|close]
# 承認は操作・checkout・branch・HEAD・repo・PR 番号に紐づき、TTL で失効する。
# guard hook（block-dangerous-in-bash.sh の gh-pr-merge-close）は同じ番号を明示した
# 単独の `gh pr merge|close <番号>` だけを通す。merge 済み PR への再実行は gh 側が
# 失敗させるので、通過時に消費はしない（CI 待ち等でやり直しても再承認は不要）。
# ログは ~/.claude/push-approve.log（PUSH_APPROVE_LOG で上書き可）に記録。

set -euo pipefail

HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"

PR_NUMBER="${1:-}"
REASON="${2:-}"
ACTION="${3:-merge}"

case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "ERROR: PR 番号（数字）を指定してください"
    echo "Usage: approve-pr <PR番号> \"理由\" [merge|close]"
    echo "例: approve-pr 127 \"ユーザーが merge を明示的に許可\""
    exit 1
    ;;
esac
if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  echo "Usage: approve-pr <PR番号> \"理由\" [merge|close]"
  exit 1
fi

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
FLAG=$(pr_approved_flag)
LOG="${PUSH_APPROVE_LOG:-$HOME/.claude/push-approve.log}"
mkdir -p "$(dirname "$LOG")"

TARGET=$(printf 'gh pr %s %s' "$ACTION" "$PR_NUMBER" | python3 "$_REPO_TARGET_CLI" pr-target)
umask 077
printf '%s\n' "$TARGET" > "$FLAG"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] APPROVE-PR repo=$GIT_ROOT pr=#$PR_NUMBER source=local-agent-record native_permission=unobserved scope=$TARGET reason=\"$REASON\"" >> "$LOG"

echo "✓ PR #$PR_NUMBER の $ACTION のローカル承認記録を作成しました（native permission は未確認）"
echo "  理由: $REASON"
echo "  対象: $TARGET"
echo "  失効: ${PR_APPROVAL_TTL_SECONDS:-1800} 秒後（承認した操作だけが通る）"
echo "  ログ: $LOG"

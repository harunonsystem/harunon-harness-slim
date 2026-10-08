#!/bin/bash
# git push の承認フラグを立てる。
# Usage: approve-push "理由" ["git push <remote> <refspec>"]
# 現在の HEAD の push を許可する。承認は HEAD が remote-tracking ref に到達した時点
# （= push 成功）か、PUSH_APPROVAL_TTL_SECONDS（既定 1800 秒）経過で失効する。
# guard hook 通過時には消費しないので、pre-push hook が落ちても再承認は不要。
# 例外は remote ref の削除だけの push（HEAD を送らず到達で閉じない）で、guard 通過時に消費する。
# ログは ~/.claude/push-approve.log（PUSH_APPROVE_LOG で上書き可）に記録。

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"

usage() {
  echo "Usage: approve-push \"理由\" [\"git push <remote> <refspec>\"]"
  echo "例: approve-push \"ユーザーがpushを明示的に許可\""
  echo "削除: approve-push \"理由\" \"git push origin --delete refs/heads/old-branch\"（単独の完全修飾 branch ref のみ）"
}

REASON="${1:-}"
PUSH_COMMAND="${2:-git push}"

# 第 1 引数は無条件に理由として記録されるため、--help を素通しすると
# 「理由: --help」で承認が成立する（2026-09-10 に実際に発生）。先に弾く。
case "$REASON" in
  -h|--help)
    usage
    exit 0
    ;;
esac

if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  usage
  exit 1
fi

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
FLAG=$(push_approved_flag)
HEAD=$(git rev-parse HEAD 2>/dev/null)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
LOG="${PUSH_APPROVE_LOG:-$HOME/.claude/push-approve.log}"
mkdir -p "$(dirname "$LOG")"

TARGET=$(printf '%s' "$PUSH_COMMAND" | python3 "$_REPO_TARGET_CLI" push-target)
# The record constrains existing user consent; a reason string is not proof of it.
umask 077
printf '%s\n' "$TARGET" > "$FLAG"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] APPROVE repo=$GIT_ROOT branch=$BRANCH head=${HEAD:0:7} source=local-agent-record native_permission=unobserved scope=$TARGET reason=\"$REASON\"" >> "$LOG"

echo "✓ push のローカル承認記録を作成しました（native permission は未確認）"
echo "  理由: $REASON"
echo "  対象: $TARGET"
echo "  失効: HEAD ${HEAD:0:7} が対象 remote/ref に到達した時点、または ${PUSH_APPROVAL_TTL_SECONDS:-1800} 秒後（削除だけの push は guard 通過で消費）"
echo "  ログ: $LOG"

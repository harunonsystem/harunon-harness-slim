#!/bin/bash
# Bypass for Codex review gate.
# Usage: codex-review-bypass "reason for skipping"          # 人手の bypass（ユーザー確認が前提）
#        codex-review-bypass --quota "companion error"     # quota / credit 切れの SKIP（Claude が自動で記録してよい唯一の経路）
# Logs bypass to ~/.claude/codex-review-bypass.log for accountability.
# --quota は理由に `quota-skip:` 接頭辞を付けてログに残し、人手の bypass と区別できるようにする。
# PR 本文に「Codex review: SKIP（quota）」と書く義務は rules/codex-review-policy.md 側。

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では Codex レビューゲート自体を課さないため、bypass 記録も不要。
[ "$(rigor_profile)" = "casual" ] && exit 0

QUOTA_SKIP=0
if [ "${1:-}" = "--quota" ]; then
  QUOTA_SKIP=1
  shift
fi
REASON="${1:-}"

if [ -z "$REASON" ]; then
  echo "ERROR: 理由を指定してください"
  echo "Usage: codex-review-bypass \"理由\""
  echo "       codex-review-bypass --quota \"companion のエラー要旨\""
  echo "例: codex-review-bypass \"ドキュメントのみの変更\""
  echo "例: codex-review-bypass \"Codex MCP障害中 - 緊急hotfix\""
  echo "例: codex-review-bypass --quota \"usage limit reached until 2026-09-12T00:00Z\""
  exit 1
fi
[ "$QUOTA_SKIP" -eq 1 ] && REASON="quota-skip: $REASON"

git rev-parse --show-toplevel > /dev/null 2>&1 || { echo "ERROR: gitリポジトリ内で実行してください"; exit 1; }
LOG="$HOME/.claude/codex-review-bypass.log"

# Core Workflow が進行中なら、legacy flag だけでは PR gate が kernel に委譲して review phase
# で止まり続ける。quota SKIP は kernel の review.skip イベントにも記録して publish へ進める。
# state.json が無い / 進行中タスクが無い場合は legacy flag だけで足りる。
record_quota_skip_in_workflow() {
  local kernel state_file repo_root inspect phase revision request result code
  kernel="${HARNESS_POLICY_KERNEL:-$HOOK_DIR/../policy/harnessctl.py}"
  state_file="$(git rev-parse --absolute-git-dir)/harness/state.json"
  [ -f "$kernel" ] && [ -f "$state_file" ] || return 0
  repo_root=$(git rev-parse --show-toplevel)
  inspect=$(jq -n --arg repo "$repo_root" '{"repo":$repo}' | python3 "$kernel" inspect 2>/dev/null) || return 0
  phase=$(printf '%s' "$inspect" | jq -r '.state.phase // empty')
  revision=$(printf '%s' "$inspect" | jq -r '.state.revision // empty')
  # task_is_active（kernel の SSOT）と同じ判定: complete 済み・着手前は進行中ではない
  if [ -z "$phase" ] || [ "$phase" = "complete" ] || [ -z "$revision" ] || [ "$revision" = "0" ]; then
    return 0
  fi
  if [ "$phase" != "review" ]; then
    # bash 3.2 は `$phase）` の全角括弧を変数名の続きとして読むので必ず braces で閉じる
    echo "ERROR: Core Workflow が review phase ではありません（phase=${phase}）。quota SKIP は review phase でだけ記録できます" >&2
    return 1
  fi
  request=$(jq -n --arg repo "$repo_root" --argjson rev "$revision" --arg reason "$1" '{
    "repo": $repo,
    "type": "review.skip",
    "expectedRevision": $rev,
    "evidence": {"kind": "review-skipped", "trust": "audit-only", "provider": "codex", "skipReason": "quota", "reason": $reason}
  }')
  if ! result=$(printf '%s\n' "$request" | python3 "$kernel" apply 2>&1); then
    code=$(printf '%s' "$result" | jq -r '.code // empty' 2>/dev/null || echo "")
    echo "ERROR: Core Workflow への quota SKIP 記録に失敗しました（${code:-$result}）" >&2
    return 1
  fi
  echo "  Core Workflow: review.skip を記録（phase → publish）"
}

if [ "$QUOTA_SKIP" -eq 1 ]; then
  record_quota_skip_in_workflow "$REASON" || exit 1
fi

codex_review_record_bypass "$REASON" "$LOG"

if [ "$QUOTA_SKIP" -eq 1 ]; then
  echo "⚠ Codex レビューを quota 切れで SKIP しました（gate flag を記録）"
  echo "  理由: $REASON"
  echo "  ログ: $LOG"
  echo "  PR 本文に「Codex review: SKIP（quota）」を書いてください"
else
  echo "⚠ Codexレビューゲートをバイパスしました"
  echo "  理由: $REASON"
  echo "  ログ: $LOG"
fi

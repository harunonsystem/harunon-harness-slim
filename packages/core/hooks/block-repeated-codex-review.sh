#!/bin/bash
# PreToolUse:Bash — Codex レビューの 2 回目以降を独断実行させないための機械的ガード
#
# 1 回目: そのまま通す + PostToolUse で flag を立てる (set-codex-review-flag.sh)
# 2 回目以降: このフックが block し、ユーザー確認を要求する
# 再実行が必要なら flag ファイル ($CODEX_REVIEW_FLAG_DIR/.codex-review-done-$KEY、既定 ~/.claude/review-gate/) をユーザー指示のもとで削除する

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"
# 存在確認してから source する（`source 不在ファイル || true` は bash 3.2 の
# set -e 下では || true が効かず即 exit 1 で落ちる既知の癖があるため、
# unreadable のケースでは source 自体を呼ばずに避ける）。
if [ -r "$HOOK_DIR/lib/denial-log.sh" ]; then
  # shellcheck source=lib/denial-log.sh
  source "$HOOK_DIR/lib/denial-log.sh"
fi

# casual profile では再レビューゲートを課さない（ADR-009）。
[ "$(rigor_profile)" = "casual" ] && exit 0

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if ! _codex_review_command_matches "$CMD"; then
  exit 0
fi

# CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# 解決不能なら対象 repo のレビュー状態を確定できないため deny する。
if ! review_gate_resolve_target_repo "$CMD"; then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-repeated-codex-review" "repeated-review-no-repo" "$CMD" || true
  jq -n --arg reason "$REVIEW_GATE_UNRESOLVABLE_REASON" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCK: レビュー対象 repo を確定できません（" + $reason + "）。対象 repo に cd してから実行してください。")
    }
  }'
  exit 0
fi

# レビュー対象が空のまま回すと Codex は何も見ずに返り、done フラグだけが立って
# 「レビュー済み」で PR gate を通ってしまう。base 取り違えの空 diff をここで止める。
if codex_review_target_is_empty "$CMD"; then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-repeated-codex-review" "review-empty-target" "$CMD" || true
  jq -n --arg label "$CODEX_REVIEW_EMPTY_TARGET_LABEL" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCK: レビュー対象が空です。companion がこのコマンドで見る対象は " + $label + " で、Codex は何も読まずに返ります（レビュー済みフラグだけが立ち、PR gate を素通りします）。`git status --porcelain` と `git diff <base>...HEAD --stat` の実出力を確認し、--base / --scope の指定かブランチを直してから再実行してください。")
    }
  }'
  exit 0
fi

FLAG=$(codex_review_done_flag)

if [ -f "$FLAG" ]; then
  # done flag の 2 行目（記録時 HEAD）を読む。旧フォーマット（タイムスタンプのみ）
  # では 2 行目が無い → 従来通り deny（後方互換）。
  RECORDED_HEAD=$(sed -n '2p' "$FLAG" 2>/dev/null || true)

  if [ -n "$RECORDED_HEAD" ] && git rev-parse --show-toplevel > /dev/null 2>&1; then
    # 記録済み HEAD が現在の履歴の祖先でなければ、同名ブランチの削除→再作成による
    # stale flag と判断し、flag を削除して allow する。
    if ! git merge-base --is-ancestor "$RECORDED_HEAD" HEAD 2>/dev/null; then
      rm -f "$FLAG"
      exit 0
    fi
  fi

  declare -f record_denial >/dev/null 2>&1 && record_denial "block-repeated-codex-review" "repeated-review" "$CMD" || true
  jq -n '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "BLOCK: Codex レビュー 2 回目以降を独断実行禁止 (rules/codex-review-policy.md)。1 回目の結果をユーザーに提示し、指示を仰ぐこと。ユーザーが明示的に再レビューを指示した場合のみ `~/.claude/hooks/codex-review-reset.sh \"理由\"` で flag を削除して再実行する（reset は ~/.claude/codex-review-reset.log に記録される）。"
    }
  }'
  exit 0
fi

exit 0

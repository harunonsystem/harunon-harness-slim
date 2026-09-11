#!/bin/bash
# PreToolUse:Bash — block gh pr create unless Codex review covers current HEAD
# Works with both raw `gh` and rtk-rewritten `rtk gh` commands.

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/review-router.sh
source "$HOOK_DIR/lib/review-router.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"
# 存在確認してから source する（`source 不在ファイル || true` は bash 3.2 の
# set -e 下では || true が効かず即 exit 1 で落ちる既知の癖があるため、
# unreadable のケースでは source 自体を呼ばずに避ける）。
if [ -r "$HOOK_DIR/lib/denial-log.sh" ]; then
  # shellcheck source=lib/denial-log.sh
  source "$HOOK_DIR/lib/denial-log.sh"
fi

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only trigger on gh pr create (including rtk-rewritten form)。
# env 代入プレフィックス（GH_REPO=owner/repo gh pr create 等）を経由しても
# 起点直後に隣接させて検出できるよう、先頭の NAME=value 列を許容する
# （P0-C: GH_REPO= を見落とすとこの hook 自体が発火せず gh 検査が素通りする）。
if ! echo "$CMD" | grep -qE '(^|&&|;|\|)\s*([A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(gh|rtk gh)\s+pr\s+create'; then
  exit 0
fi

# hook は Claude Code の CWD で実行されるため、CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# 解決不能なら deny する（rigor profile 判定より前に倒す。casual repo に cd するだけで
# gate ごと消える P2 の穴を塞ぐため、判定順は load-bearing）。
if ! review_gate_resolve_target_repo "$CMD"; then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-pr-without-codex-review" "pr-without-review-no-repo" "$CMD" || true
  jq -n --arg reason "$REVIEW_GATE_UNRESOLVABLE_REASON" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCKED: PR 作成対象 repo を確定できません（" + $reason + "）。対象 repo に cd してから実行してください。")
    }
  }'
  exit 0
fi

# Skip if not in a git repo
git rev-parse --show-toplevel > /dev/null 2>&1 || exit 0

# gh pr create -R/--repo/GH_REPO=/--head での別 repo・別ブランチへの PR 作成は
# レビュー証跡（repo root + branch + HEAD）と対応付けられないため deny する。
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if ! GH_TARGET_REASON=$(printf '%s' "$CMD" | python3 "$HOOK_DIR/../policy/repo_target.py" gh-target --current-branch "$CURRENT_BRANCH" 2>&1); then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-pr-without-codex-review" "pr-without-review-no-repo" "$CMD" || true
  jq -n --arg reason "$GH_TARGET_REASON" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCKED: " + $reason)
    }
  }'
  exit 0
fi

# casual profile では Codex レビューゲートを課さない（ADR-009）。resolve 済みの
# 対象 repo で判定する（P2: 解決前の repo で判定していたのを修正）。
[ "$(rigor_profile)" = "casual" ] && exit 0

# 段階導入中の既存タスクを壊さず、Core 開始済みタスクだけ追加 gate を課すため。
KERNEL="${HARNESS_POLICY_KERNEL:-$HOOK_DIR/../policy/harnessctl.py}"
STATE_FILE="$(git rev-parse --absolute-git-dir)/harness/state.json"
if [ -f "$KERNEL" ] && [ -f "$STATE_FILE" ]; then
  set +e
  # プロセス cwd 依存をやめ、解決済みの対象 repo と command を明示的に渡す
  # （Resolution Responsibility: 解決結果を kernel 側で再解決させない）。
  REPO_ROOT=$(git rev-parse --show-toplevel)
  KERNEL_REQUEST=$(jq -n --arg repo "$REPO_ROOT" --arg cmd "$CMD" '{"action":"pr.create","repo":$repo,"command":$cmd}')
  KERNEL_RESULT=$(printf '%s\n' "$KERNEL_REQUEST" | python3 "$KERNEL" authorize 2>&1)
  KERNEL_STATUS=$?
  set -e
  # complete 済み / 着手前で放置された state は「進行中タスク無し」（kernel の
  # task_is_active が SSOT）。state.json が無い場合と同じく下の legacy gate に落とす。
  KERNEL_CODE=$(printf '%s' "$KERNEL_RESULT" | jq -r '.code // empty' 2>/dev/null || echo "")
  if [ "$KERNEL_CODE" != "WORKFLOW_INACTIVE" ]; then
    if [ "$KERNEL_STATUS" -ne 0 ]; then
      declare -f record_denial >/dev/null 2>&1 && record_denial "block-pr-without-codex-review" "pr-without-review" "$CMD" || true
      jq -n --arg reason "$KERNEL_RESULT" '{
        "hookSpecificOutput": {
          "hookEventName": "PreToolUse",
          "permissionDecision": "deny",
          "permissionDecisionReason": ("BLOCKED: Core Workflow PR gate rejected: " + $reason)
        }
      }'
      exit 0
    fi
    # Core Workflow 開始後は state + current HEAD evidence が唯一の判定元。
    # /tmp の legacy flag と二重判定すると runtime 間で結果が分岐するため、ここで終了する。
    exit 0
  fi
fi

# 機械分類: none/bypass は Codex レビュー不要と判定し、legacy flag 判定をスキップする。
# デフォルトブランチが解決できない場合は router を呼ばず従来動作にフォールバックする。
DEFAULT_BRANCH=$(_codex_review_default_branch)
if [ -n "$DEFAULT_BRANCH" ]; then
  MERGE_BASE=$(git merge-base "$DEFAULT_BRANCH" HEAD 2>/dev/null || echo "")
  if [ -n "$MERGE_BASE" ]; then
    DIFF_NAME_STATUS=$(git diff --name-status "$MERGE_BASE"...HEAD 2>/dev/null || echo "")
    NUMSTAT_TOTAL=$(git diff --numstat "$MERGE_BASE"...HEAD 2>/dev/null | awk '{add+=$1; del+=$2} END {print add+del+0}')
    COMMIT_SUBJECTS=$(git log --format=%s "$MERGE_BASE"...HEAD 2>/dev/null || echo "")
    ROUTE=$(printf '%s\n' "$DIFF_NAME_STATUS" | review_route "$NUMSTAT_TOTAL" "$COMMIT_SUBJECTS")

    case "$ROUTE" in
      none)
        exit 0
        ;;
      bypass)
        codex_review_record_bypass "auto: $ROUTE" "$HOME/.claude/codex-review-bypass.log"
        exit 0
        ;;
    esac
  fi
fi

FLAG=$(codex_review_gate_flag)

if [ ! -f "$FLAG" ]; then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-pr-without-codex-review" "pr-without-review" "$CMD" || true
  jq -n '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "BLOCKED: Codexレビュー未実施。先に `/codex:review` を実行し、その後まったく同じコマンドを再実行してください。--head / --repo / --base を付け替えた別の形で通そうとしないでください（その形も別の理由で deny されます）。"
    }
  }'
  exit 0
fi

REVIEWED_HEAD=$(cat "$FLAG")
CURRENT_HEAD=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

if [ "$REVIEWED_HEAD" != "$CURRENT_HEAD" ]; then
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-pr-without-codex-review" "pr-without-review" "$CMD" || true
  jq -n --arg reviewed "$REVIEWED_HEAD" --arg current "$CURRENT_HEAD" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": ("BLOCKED: レビュー後に新しいコミットがあります（reviewed: " + $reviewed[0:7] + " / current: " + $current[0:7] + "）。2 周目のレビューはユーザーの明示指示が要ります（rules/codex-review-policy.md）。まずユーザーに「再レビューするか、このまま PR にして残りをフォローアップに回すか」を聞いてください。独断で `/codex:review` を再実行しないでください。")
    }
  }'
  exit 0
fi

# Codex review done and HEAD matches — allow
exit 0

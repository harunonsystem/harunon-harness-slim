#!/bin/bash
# claude-worktree-create.sh（gwm）の対になる WorktreeRemove hook。
# hook が無いと Claude は `git worktree remove --force` に fallback し、gwm が作った
# branch は消さない（docs: hooks#worktreeremove）。ここでは未保存の作業を失わない範囲だけ消す:
#   1. 未 commit 変更（untracked・ignored・submodule 内を含む）があれば拒否
#   2. submodule にどの remote にも無い commit があれば拒否
#   3. 1-2 を通ったときだけ --force で remove（submodule を含む worktree は --force 必須）
#   4. branch は merge 済みのときだけ `git branch -d` で消す（-D は使わない）
# 拒否は exit 1。directory が残るので Claude は削除失敗として扱い、worktree はそのまま残る。
set -euo pipefail

refuse() {
  echo "[gwm worktree] 削除しません: $*" >&2
  exit 1
}

command -v jq >/dev/null 2>&1 || refuse "jq が必要です"

WT="$(jq -r '.worktree_path // empty')"
[ -n "$WT" ] || refuse "WorktreeRemove input に worktree_path がありません"
[ -d "$WT" ] || exit 0

GIT_DIR="$(git -C "$WT" rev-parse --path-format=absolute --git-dir 2>/dev/null)" \
  || refuse "git worktree ではありません: $WT"
COMMON_DIR="$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir)"
[ "$GIT_DIR" != "$COMMON_DIR" ] || refuse "linked worktree ではなくメイン checkout です: $WT"
MAIN="$(dirname "$COMMON_DIR")"

DIRTY="$(git -C "$WT" status --porcelain --ignored --untracked-files=all --ignore-submodules=none)"
[ -z "$DIRTY" ] || refuse "未 commit の変更があります: $WT
$DIRTY"

SUB_DIRTY="$(git -C "$WT" submodule foreach --quiet --recursive \
  'dirty=$(git status --porcelain --ignored --untracked-files=all) || exit; if [ -n "$dirty" ]; then printf "%s\n%s\n" "$displaypath" "$dirty"; fi')"
[ -z "$SUB_DIRTY" ] || refuse "submodule に未保存の変更・ignored ファイルがあります:
$SUB_DIRTY"

UNPUSHED="$(git -C "$WT" submodule foreach --quiet --recursive \
  'if [ -n "$(git rev-list -n 1 HEAD --not --remotes)" ]; then echo "$displaypath"; fi')"
[ -z "$UNPUSHED" ] || refuse "submodule に remote へ未 push の commit があります: $UNPUSHED"

for state in rebase-merge rebase-apply BISECT_LOG MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [ ! -e "$GIT_DIR/$state" ] || refuse "進行中の git 操作（${state}）があります: $WT"
done

BRANCH="$(git -C "$WT" symbolic-ref --quiet --short HEAD || true)"
if [ -z "$BRANCH" ]; then
  # detached HEAD の commit は worktree を消すとどの ref からも辿れなくなる。
  ORPHAN="$(git -C "$WT" rev-list -n 1 HEAD --not --branches --remotes --tags)"
  [ -z "$ORPHAN" ] || refuse "detached HEAD に branch / remote / tag から辿れない commit があります: $ORPHAN"
fi

git -C "$MAIN" worktree remove --force "$WT"

if [ -n "$BRANCH" ]; then
  if ! git -C "$MAIN" branch -d "$BRANCH" >/dev/null 2>&1; then
    echo "[gwm worktree] branch $BRANCH は未 merge のため残します（不要なら手動で削除）" >&2
  fi
fi

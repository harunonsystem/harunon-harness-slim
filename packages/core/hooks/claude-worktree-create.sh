#!/bin/bash
# Claude の新規 worktree 作成を gwm に委譲する WorktreeCreate hook。
# EnterWorktree の path 形式ではなく新規作成として扱うため、外部 worktree の確認を発生させない。
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "[gwm worktree] jq が必要です" >&2
  exit 1
fi
if ! command -v gwm >/dev/null 2>&1; then
  echo "[gwm worktree] gwm が必要です" >&2
  exit 1
fi

INPUT=$(cat)
NAME=$(printf '%s' "$INPUT" | jq -r '.name // empty')
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')

if [ -z "$NAME" ]; then
  echo "[gwm worktree] WorktreeCreate input に name がありません" >&2
  exit 1
fi
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
  echo "[gwm worktree] WorktreeCreate input の cwd が存在しません: $CWD" >&2
  exit 1
fi

# cwd が submodule 内を指す場合は最外殻の superproject に寄せる。
# worktree は「cwd を含む最も外側のリポジトリ」に対して作る: submodule は
# 親リポジトリの部品で、distribute 等の親側フローは親 checkout 内の submodule
# パスを読むため、submodule 単体の worktree を作っても届かない。実害あり
# （2026-07-26: 調査で cd した packages/extras/_active が session cwd に残り、
# extras 側の worktree が作られた）。ネストした submodule もループで最外殻まで辿る。
while SUPERPROJECT="$(git -C "$CWD" rev-parse --show-superproject-working-tree 2>/dev/null)" \
      && [ -n "$SUPERPROJECT" ]; do
  echo "[gwm worktree] cwd は submodule 内のため superproject に寄せます: $CWD -> $SUPERPROJECT" >&2
  CWD="$SUPERPROJECT"
done

# base は remote の default branch（Claude 標準の worktree.baseRef=fresh と同じ意味論）。
# gwm add の既定はローカル main 起点で、ローカルにしか無い未 push commit が新 branch に
# 混ざり、PR が別 PR と conflict する実害があった（2026-08-28: PR #126）。
# origin が無い repo（ローカル専用・テスト fixture）は従来どおり gwm の既定に任せる。
FROM_ARGS=()
if DEFAULT_REF="$(git -C "$CWD" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)"; then
  if ! git -C "$CWD" fetch --quiet origin "${DEFAULT_REF#origin/}" 2>/dev/null; then
    echo "[gwm worktree] origin の fetch に失敗したため、手元の $DEFAULT_REF を base にします" >&2
  fi
  FROM_ARGS=(--from "$DEFAULT_REF")
fi

# gwm の通常出力はパスだけだが、post_create hook 等が stdout に出力しても
# Claude の契約どおり最後の空でない行だけを worktree path として返す。
# シェル統合用の環境変数が親プロセスから渡っても、Claude が読める stdout を優先する。
unset GWM_CWD_FILE GWM_HOOKS_FILE
GWM_OUTPUT="$(cd "$CWD" && gwm add "${FROM_ARGS[@]+"${FROM_ARGS[@]}"}" "$NAME")"
WORKTREE_PATH="$(printf '%s\n' "$GWM_OUTPUT" | awk 'NF { path = $0 } END { print path }')"

case "$WORKTREE_PATH" in
  /*) ;;
  *)
    echo "[gwm worktree] gwm が絶対パスを返しませんでした: $WORKTREE_PATH" >&2
    exit 1
    ;;
esac
if [ ! -d "$WORKTREE_PATH" ]; then
  echo "[gwm worktree] gwm が返した worktree が存在しません: $WORKTREE_PATH" >&2
  exit 1
fi

printf '%s\n' "$WORKTREE_PATH"

#!/bin/bash
# PreToolUse:Bash — git push 前にローカル確認を促す
set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"

INPUT=$(cat)

# Fast path: skip if command doesn't contain "push"
case "$INPUT" in
  *push*) ;;
  *) exit 0 ;;
esac

# 壊れた JSON でも fail-open（jq のパース失敗で hook がクラッシュしないよう空にフォールバック）
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")

if ! echo "$CMD" | grep -qE '(^|&&|;|\|)\s*(git|rtk git)\s+push'; then
  exit 0
fi

# `cd /path/to/repo-b && git push` を repo A から実行しても hook 自体の cwd は
# repo A のまま。解決せずに status を読むと push 対象ではない repo の変更を
# 「この PR に含めるべきか」と警告することになる（2026-09-05 の Codex review P2）。
# 解決できた場合だけ対象 repo の状態を読む。
TARGET_RESOLVED=0
if review_gate_resolve_target_repo "$CMD"; then
  TARGET_RESOLVED=1
fi

git rev-parse --show-toplevel &>/dev/null || exit 0

REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

SSH_CHECK=""
if echo "$REMOTE" | grep -q "^https://"; then
  SSH_CHECK=" ⚠ remote が HTTPS です（SSH 推奨: git remote set-url origin git@github.com:...）"
fi

# 未 commit のファイルを列挙する。PR に載せるつもりの変更が commit 漏れのまま
# push され、CI が落ちてから気づくケースがあったため、push 直前に実物を出す
# （deny ではなく提示に留める。意図的に除外する変更も正当なため）。
# 対象 repo を確定できなかった場合は列挙しない — 別 repo のファイル名を出すのは
# 何も出さないより有害。
DIRTY=""
if [ "$TARGET_RESOLVED" = "1" ]; then
  DIRTY=$(git status --porcelain 2>/dev/null | head -20 || echo "")
fi
DIRTY_NOTE=""
if [ -n "$DIRTY" ]; then
  DIRTY_NOTE=" ⚠ 未 commit の変更があります（この PR に含めるべきか 1 件ずつ確認し、除外するなら理由を述べること。無言で落とさない）:
$DIRTY"
fi

jq -n --arg branch "$BRANCH" --arg sshcheck "$SSH_CHECK" --arg dirty "$DIRTY_NOTE" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": ("PUSH前チェック: push 元ブランチ=\($branch)。意図した機能ブランチか確認。ローカル/Storybook/ブラウザで動作確認済みか。CSS修正の場合レンダリングに反映されているか目視したか。\($sshcheck)\($dirty)")
  }
}'

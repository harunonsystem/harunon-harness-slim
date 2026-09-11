#!/bin/bash
# PreToolUse:Bash — git commit 前に全体調査・確認を促すプロンプト
set -euo pipefail

INPUT=$(cat)

# Fast path: skip if command doesn't contain "commit"
case "$INPUT" in
  *commit*) ;;
  *) exit 0 ;;
esac

# 壊れた JSON でも fail-open（jq のパース失敗で hook がクラッシュしないよう空にフォールバック）
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# lib 不在は配布漏れ。commit 判定そのものが崩れた状態で素通しにしないため、
# required hook として判定層の消失を allow に倒さず deny にする。
NORMALIZE_LIB="$HOOK_DIR/lib/command-normalize.sh"
if [ ! -r "$NORMALIZE_LIB" ]; then
  echo "commit 前チェックに必要な lib が読めません: ${NORMALIZE_LIB}（安全側に倒してブロックします）" >&2
  exit 2
fi
# shellcheck source=lib/command-normalize.sh
source "$NORMALIZE_LIB"

# commit 検出は共通の境界正規化に乗せる（改行 / & / subshell / $( ) を起点として扱い、
# git のグローバルオプション `-C <path>` は正規化側が剥がす）。
if ! normalize_command_available; then
  echo "commit 前チェックに必要な perl が見つかりません（安全側に倒してブロックします）" >&2
  exit 2
fi
origin_rc=0
command_origin_matches "$CMD" '(git|rtk git)[[:space:]]+commit([^A-Za-z0-9_-]|$)' || origin_rc=$?
case $origin_rc in
  0) ;;
  1) exit 0 ;;
  *)
    echo "commit 前チェックのコマンド前処理に失敗しました（安全側に倒してブロックします）" >&2
    exit 2
    ;;
esac

# --- commit の対象 repo を解決する。hook プロセスの cwd で git diff --cached /
# git branch --show-current を実行すると、`cd /repo-b && git commit ...` や
# `git -C /repo-b commit ...` の形で別リポジトリを commit しているときに
# hook 自身の cwd（= 呼び出し元 repo）を見てしまい、判定が的外れになる。
# 優先順位: (a) commit を打つ git 呼び出し自身の -C <path> → (b) commit 呼び出し
# より前にある最後の `cd <path> &&` → (c) どちらも無ければ cwd。
# パスのクォート処理は最小限（既存の commit 検出ロジック同様、raw テキストの
# 正規表現マッチに留め、shlex 相当の厳密なトークン化はしない）。
TARGET=$(printf '%s' "$CMD" | perl -ne '
  if (/(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+-C\s+(\S+)\s+commit\b/) {
    print $1;
    exit;
  }
  if (/^(.*?)(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+commit\b/s) {
    my $prefix = $1;
    if ($prefix =~ /cd\s+(\S+)\s*$/) {
      print $1;
    }
  }
')
TARGET="${TARGET%\"}"; TARGET="${TARGET#\"}"
TARGET="${TARGET%\'}"; TARGET="${TARGET#\'}"
TARGET="${TARGET:-$(pwd)}"

git -C "$TARGET" rev-parse --show-toplevel &>/dev/null || exit 0

# staged 差分のシークレット検出は block-secrets-in-commit.sh に分離した（deny する
# 判定は runtime を問わない普遍ポリシーなので全 runtime に配る。この hook は Claude の
# additionalContext 注入が目的で、hook 移植ポリシー (b) により claude / codex 限定）。
BRANCH=$(git -C "$TARGET" branch --show-current 2>/dev/null || echo "unknown")
ROOT=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || echo "")

CONTEXT="COMMIT前チェック: (1) 現在ブランチ=${BRANCH}、worktreeルート=${ROOT}。意図した feature/issue ブランチと一致しているか。(2) 同種の問題が他にもないかgrep済みか。(3) CSS/UI変更の場合ブラウザで目視確認済みか。(4) Figma実装の場合スクショ比較済みか。全て確認済みならそのまま進めてOK。"

# --- main/master ブランチでの commit 警告（harness は main 直運用があるため warn のみ）
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  CONTEXT="${CONTEXT} main/master への commit です。push は通らないため、回収するなら \`git push origin HEAD:refs/heads/<branch>\` で feature branch を作り → PR → \`git switch main && git reset --hard origin/main\` の手順を使ってください。"
fi

# --- sandbox/ 配下での非 ASCII commit message 警告（OSS contribution は英語で）
CWD="$TARGET"
if echo "$CWD" | grep -qE '(^|/)sandbox(/|$)'; then
  if printf '%s' "$CMD" | perl -0777 -ne 'exit(/[^\x00-\x7F]/ ? 0 : 1)'; then
    CONTEXT="${CONTEXT} cwd が sandbox 配下で commit message に非 ASCII が含まれています。OSS contribution は英語 commit message にしてください。"
  fi
fi

jq -n --arg ctx "$CONTEXT" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": $ctx
  }
}'

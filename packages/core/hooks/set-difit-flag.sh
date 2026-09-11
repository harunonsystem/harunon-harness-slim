#!/bin/bash
# PostToolUse:Bash — difit 実行成功時に difit-done flag を立てる
# - block-commit-without-difit.sh と対（difit 完了後の commit を通す）

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile ではフラグを立てない（対応する gate 自体を課さないため）。
[ "$(rigor_profile)" = "casual" ] && exit 0

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if ! echo "$CMD" | grep -qE '(^|&&|;|\|)\s*((npx|bunx)[[:space:]]+)?difit\b'; then
  exit 0
fi

# 中断・失敗時は flag を立てない（環境エラーで done になり、次回 commit が
# 誤って通ってしまうのを避ける。set-codex-review-flag.sh と同じ防御方針）。
INTERRUPTED=$(echo "$INPUT" | jq -r '.tool_response.interrupted // false')
EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exitCode // .tool_response.exit_code // empty')

if [ "$INTERRUPTED" = "true" ]; then
  exit 0
fi
if [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ]; then
  exit 0
fi

# hook は Claude Code の CWD で実行される。CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# 解決不能なら誤った repo に「difit 済み」を書きかねないため、書かずに exit 0 する。
if ! review_gate_resolve_target_repo "$CMD"; then
  exit 0
fi

git rev-parse --show-toplevel > /dev/null 2>&1 || exit 0

# flag には2行のフィンガープリントを書く（タイムスタンプではなくレビュー対象 diff に紐付ける）。
# 1行目: staged diff のハッシュ（difit --staged 相当のワークフロー）
# 2行目: HEAD からの全diff（staged+unstaged）のハッシュ（difit を working tree 全体に掛けるワークフロー）
# block-commit-without-difit.sh は commit 時の `git diff --cached` ハッシュを
# このいずれかと突き合わせ、difit 後に diff が変わっていないかを検証する。
{
  git diff --cached 2>/dev/null | shasum | awk '{print $1}'
  git diff HEAD 2>/dev/null | shasum | awk '{print $1}'
} > "$(difit_done_flag)"

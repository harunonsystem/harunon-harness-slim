#!/bin/bash
# PostToolUse:Bash — Codex レビュー実行後に flag を立てる
# - done フラグ: block-repeated-codex-review.sh と対（2 回目以降のブロック）
# - gate フラグ: block-pr-without-codex-review.sh と対（PR ゲート解錠、HEAD を記録）
#   レビュー本体（codex-companion.mjs review）の Bash 完了時点で立てる。
#   Skill 起動時点で立てると、レビューが中断・失敗しても PR ゲートが開いてしまう。

set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if ! _codex_review_command_matches "$CMD"; then
  exit 0
fi

# レビューが実行に失敗した場合は flag を立てない（環境エラーで done になると
# 再実行が block-repeated-codex-review.sh に弾かれ、手動 flag 削除が必要になる。
# 実例: sqlite state runtime 初期化エラー 2026-07-03 / 07-08 / 07-09 / 07-10）。
# 判定は (1) 中断 (2) exit code 非 0（フィールドが存在する場合のみ）
# (3) 環境エラーの既知シグネチャ、の順。成功時の誤検知を避けて保守的に。
INTERRUPTED=$(echo "$INPUT" | jq -r '.tool_response.interrupted // false')
EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exitCode // .tool_response.exit_code // empty')
OUTPUT=$(echo "$INPUT" | jq -r '(.tool_response.stdout // "") + "\n" + (.tool_response.stderr // "")')

REVIEW_FAILED=""
if [ "$INTERRUPTED" = "true" ]; then
  REVIEW_FAILED="レビューが中断された"
elif [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ]; then
  REVIEW_FAILED="レビューコマンドが exit ${EXIT_CODE} で失敗"
elif echo "$OUTPUT" | grep -qiE 'failed to initialize .* runtime|app-server exited unexpectedly|codex: command not found'; then
  REVIEW_FAILED="環境エラーでレビュー未実施"
fi

if [ -n "$REVIEW_FAILED" ]; then
  jq -n --arg reason "$REVIEW_FAILED" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": ("Codex レビューは失敗（" + $reason + "）のため done flag は立てていません。環境を直せばそのまま再実行できます（flag 削除は不要）。")
    }
  }'
  exit 0
fi

# hook は Claude Code の CWD で実行される。CMD 内の --cwd / cd 先に移動して正しい git context を解決する。
# 解決不能なら誤った repo に「レビュー済み」を書きかねないため、書かずに exit 0 する。
if ! review_gate_resolve_target_repo "$CMD"; then
  exit 0
fi

# casual profile ではフラグを立てない（対応する gate 自体を課さないため）。
# 解決済みの対象 repo で判定する（session cwd 基準だと flag キーの基準 repo とズレる）。
[ "$(rigor_profile)" = "casual" ] && exit 0

FLAG=$(codex_review_done_flag)

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$FLAG"

# repo 内であれば、done flag の 2 行目に記録時の HEAD を追記する（同名ブランチ
# 再作成時の stale flag 判定用。block-repeated-codex-review.sh が参照する）。
# PR ゲート用の gate flag にも同じ HEAD を記録する。
if git rev-parse --show-toplevel > /dev/null 2>&1; then
  git rev-parse HEAD >> "$FLAG" 2>/dev/null || true
  git rev-parse HEAD > "$(codex_review_gate_flag)" 2>/dev/null || true
fi
exit 0

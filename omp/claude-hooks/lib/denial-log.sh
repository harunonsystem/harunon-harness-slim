#!/bin/bash
# 共有ライブラリ: hook の deny 判定を JSONL に記録する
#
# なぜ: block 系 hook は deny 時に stderr / permissionDecision で通知するだけで、
# 判定結果の一次ソースが残らない。「どの rule が」「どれくらいの頻度で」効いているかを
# 追う手段が無く、rule の見直しや lesson memory への還流がユーザーの記憶頼みの
# 手作業になっていた。1 行 1 deny の JSONL を残せば、後から rtk grep / jq で
# 集計・追跡できる。
#
# 提供する関数:
#   record_denial <hook-name> <reason> <detail>
#     — ${HARNESS_DENIAL_LOG:-$HOME/.claude/logs/hook-denials.jsonl} に 1 行追記する。
#       detail は先頭 500 文字に切る。jq が無ければ何もしない。
#
# 契約: record_denial は advisory ログであって安全層ではない。呼び出し元
# （block-*.sh）の判定・deny の可否・exit code を一切変えてはならない。
# 内部の失敗は全て `|| return 0` で握りつぶし、呼び出し側が set -e 下で
# source していても、ログ書き込みの成否が呼び出し元の制御フローに影響しない
# ようにする（安全層の deny 判定にログ機構の不具合を巻き込まない）。

record_denial() {
  local hook="${1:-}"
  local reason="${2:-}"
  local detail="${3:-}"

  command -v jq >/dev/null 2>&1 || return 0

  local log_path="${HARNESS_DENIAL_LOG:-$HOME/.claude/logs/hook-denials.jsonl}"
  local log_dir
  log_dir="$(dirname "$log_path")"
  mkdir -p "$log_dir" 2>/dev/null || return 0

  # ログ用の目安情報でよいため、判定用 lib（command-normalize.sh）と違い
  # マルチバイト境界は気にせず bash の substring で単純に切り詰める。
  detail="${detail:0:500}"

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)" || return 0

  local line
  line="$(jq -nc \
    --arg ts "$ts" \
    --arg hook "$hook" \
    --arg reason "$reason" \
    --arg runtime "${HARNESS_RUNTIME:-}" \
    --arg cwd "$PWD" \
    --arg detail "$detail" \
    '{ts: $ts, hook: $hook, reason: $reason, runtime: $runtime, cwd: $cwd, detail: $detail}' \
    2>/dev/null)" || return 0

  [ -n "$line" ] || return 0

  printf '%s\n' "$line" >> "$log_path" 2>/dev/null || return 0

  return 0
}

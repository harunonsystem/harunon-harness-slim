#!/bin/bash
# PermissionDenied — 権限拒否（classifier / permission rule のどちらも）を JSONL で記録する。
#
# insights 2026-08: guard hook / classifier の誤検知で作業が繰り返し止まった実例が複数あり、
# 実際に拒否された tool_input / reason を貯めて regression fixture の材料にする。
# このフックは記録専用で、作業をブロックせず classifier retry も要求しない
# （何も出力せず常に exit 0）。
set -euo pipefail

LOG=~/.claude/permission-denied.log

if ! command -v jq >/dev/null 2>&1; then
  echo "[log-permission-denied] jq が必要です。ログを記録せず続行します" >&2
  exit 0
fi

INPUT=$(cat)

TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
BRANCH=$(git branch --show-current 2>/dev/null || echo "-")
PROJECT=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# ログ格納ディレクトリが無い環境（~/.claude 未作成）でもクラッシュしないよう作成する
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

printf '%s' "$INPUT" | jq -c \
  --arg ts "$TIMESTAMP" \
  --arg project "$PROJECT" \
  --arg branch "$BRANCH" \
  '
  (.tool_input // {}) as $ti
  | (if .tool_name == "Bash" then ($ti.command // "")
     else ($ti.file_path // $ti.url // "") end) as $command
  | {
      ts: $ts,
      project: $project,
      branch: $branch,
      session_id: (.session_id // ""),
      tool_name: (.tool_name // ""),
      source: (.source // ""),
      permission_mode: (.permission_mode // ""),
      reason: (.reason // ""),
      command: $command,
      tool_input: $ti
    }
  ' >> "$LOG" 2>/dev/null || true

# 直近 500 行のみ保持
if [ -f "$LOG" ]; then
  tail -500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" || true
fi

exit 0

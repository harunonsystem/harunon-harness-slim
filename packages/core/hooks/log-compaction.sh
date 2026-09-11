#!/bin/bash
# PreCompact — コンパクション発生をログに記録し、作業コンテキストを保存する
set -euo pipefail

LOG=~/.claude/compaction.log
TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
BRANCH=$(git branch --show-current 2>/dev/null || echo "-")
ROOT=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# ログ格納ディレクトリが無い環境（~/.claude 未作成）でもクラッシュしないよう作成する
mkdir -p "$(dirname "$LOG")"
echo "$TIMESTAMP compact project=$ROOT branch=$BRANCH" >> "$LOG"

# 直近 100 行のみ保持
tail -100 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

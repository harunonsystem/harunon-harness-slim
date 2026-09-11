#!/bin/bash
# PreToolUse:WebFetch — GitHub の issue/PR/Actions/Discussions ページ取得を block する。
#
# これらは gh CLI で構造化データを取れる（トークン効率・正確性ともに WebFetch の
# HTML スクレイピングより優れる）。raw.githubusercontent.com は別ドメインなので
# このガードには一致せず、そのまま素通りする。
set -euo pipefail

INPUT=$(cat)
URL=$(echo "$INPUT" | jq -r '.url // .tool_input.url // ""' 2>/dev/null || echo "")

if [ -z "$URL" ]; then
  exit 0
fi

# ホスト名は大文字小文字を区別しないため小文字化してから判定する。ホスト位置を
# スキーマ直後にアンカーすることで、パス中に "github.com" を含む別ドメイン
# （例: example.test/docs/github.com/...）を誤検知しない。
LOWER_URL=$(printf '%s' "$URL" | tr '[:upper:]' '[:lower:]')

if echo "$LOWER_URL" | command grep -qE '^https?://([^/]+\.)?github\.com/[^/]+/[^/]+/(issues|pull|actions|discussions)'; then
  cat >&2 <<'EOF'
GitHub の issue/PR/Actions/Discussions は WebFetch ではなく gh CLI を使ってください:

  gh issue view <number>
  gh pr view <number>
  gh run view <run-id>
EOF
  exit 2
fi

exit 0

#!/bin/bash
# Claude Code 起動時に期待されるプラン・org であることを検証する
# EXPECTED_PLAN / EXPECTED_ORG は環境変数で設定（未設定ならスキップ）

set -euo pipefail

EXPECTED_PLAN="${HARNESS_EXPECTED_PLAN:-}"
EXPECTED_ORG="${HARNESS_EXPECTED_ORG:-}"

if [ -z "$EXPECTED_PLAN" ] && [ -z "$EXPECTED_ORG" ]; then
  echo "OK"
  exit 0
fi

warnings=()

# --- Auth check ---
auth_json=""
if command -v gtimeout &>/dev/null; then
  auth_json=$(gtimeout 5 claude auth status --json 2>/dev/null) || true
elif command -v perl &>/dev/null; then
  auth_json=$(perl -e 'alarm 5; exec @ARGV' claude auth status --json 2>/dev/null) || true
else
  auth_json=$(claude auth status --json 2>/dev/null) || true
fi

if [ -z "$auth_json" ]; then
  echo "⚠️ claude auth status の取得に失敗（タイムアウトまたはエラー）"
  exit 0
fi

# 未ログインは plan/org 不一致とは別問題。誤った「アカウント不一致」警告を出さず
# ログイン案内だけ返す（login 前の SessionStart で毎回誤発報していた: 2026-08-09）
# フィールド欠落（古い CLI）は従来どおり plan/org 検証に進める。
# jq の // は false も null と同様に潰すため、明示比較で判定する
logged_in=$(echo "$auth_json" | jq -r 'if .loggedIn == false then "false" else "true" end')
if [ "$logged_in" != "true" ]; then
  echo "⚠️ 未ログインです。/login または claude auth login 後、plan/org は再セッションで検証されます"
  exit 0
fi

plan=$(echo "$auth_json" | jq -r '.subscriptionType // "unknown"')
org=$(echo "$auth_json" | jq -r '.orgName // ""')
email=$(echo "$auth_json" | jq -r '.email // "unknown"')

# --- Plan check（期待値が設定されている場合のみ） ---
if [ -n "$EXPECTED_PLAN" ] && [ "$plan" != "$EXPECTED_PLAN" ]; then
  warnings+=("🚨 プラン: '$plan' — 期待: '$EXPECTED_PLAN'")
fi

# --- Org check（期待値が設定されている場合のみ） ---
if [ -n "$EXPECTED_ORG" ] && [ "$org" != "$EXPECTED_ORG" ]; then
  warnings+=("🚨 Org: '${org:-なし}' — 期待: '$EXPECTED_ORG'")
fi

# --- Output ---
if [ ${#warnings[@]} -gt 0 ]; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ⚠️  Claude Code 起動チェック: アカウント不一致"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  for w in "${warnings[@]}"; do
    echo "  $w"
  done
  echo ""
  echo "  現在: $email / org: ${org:-なし} / plan: $plan"
  echo "  期待: $EXPECTED_PLAN / org: $EXPECTED_ORG"
  echo ""
  echo "  → claude auth logout && claude auth login で切り替えてください"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 0
fi

echo "OK"

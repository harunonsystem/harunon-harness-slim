#!/usr/bin/env bash
# setup-machine.sh — 新しい開発マシンの global tool / env セットアップ
#
# 既存の global mise 設定を壊さず、不足している harness 用 CLI と [env] の差分だけを
# ユーザー確認後に追加・反映する。認証・MCP接続・private extras の取得は別工程。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v mise >/dev/null 2>&1; then
  printf 'ERROR: mise が見つかりません。先に mise をインストールしてください。\n' >&2
  exit 1
fi

# global mise env 確認（scripts/mise-global-check.py）用の interpreter。この段階では
# まだ mise.toml の pin が有効な作業ディレクトリとは限らない（新規マシンの初回実行が
# 主用途）ため、bootstrap.sh の PYTHON_BIN 解決（mise which python3）とは別に、stdlib
# のみ（tomllib, Python 3.11+）で動く前提で PATH 上の python3 を使う。mise 呼び出しを
# ここで増やすと confirm_install の mise ログ検証（test_setup_machine.py）に無関係な
# 呼び出しが混入するため、意図的に mise を経由しない。
if [[ -z "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '⚠ python3 が見つかりません。global mise env の確認をスキップします\n' >&2
  PYTHON_BIN=""
fi

confirm_install() {
  local label="$1"
  local package="$2"
  local command_name="$3"

  if command -v "$command_name" >/dev/null 2>&1; then
    printf '✓ %s: %s\n' "$label" "$(command -v "$command_name")"
    return 0
  fi

  printf '⚠ %s が見つかりません。global mise に %s を追加しますか？ [y/N] ' "$label" "$package"
  if ! read -r answer; then
    # EOF は対話を継続できないため、プロンプトの既定値と同じ拒否として扱う。
    answer=""
  fi
  case "$answer" in
    y|Y|yes|YES)
      mise use --global --pin "$package"
      printf '✓ %s を追加しました\n' "$label"
      ;;
    *)
      printf '⊘ %s はスキップしました\n' "$label"
      ;;
  esac
}

printf '%s\n' '=== harness machine setup ==='
printf '例: %s\n\n' "$REPO_ROOT/mise.global.example.toml"

confirm_install "Pi" "npm:@earendil-works/pi-coding-agent" "pi"
confirm_install "difit" "npm:difit" "difit"
# ocr-review skill が canonical な diff レビュー engine として呼ぶ CLI。
# mise.global.example.toml に宣言しただけでは新規マシンに入らないので、ここでも尋ねる。
confirm_install "OpenCodeReview" "npm:@alibaba-group/open-code-review" "ocr"

if [[ -n "$PYTHON_BIN" ]]; then
  printf '\n'
  "$PYTHON_BIN" "$REPO_ROOT/scripts/mise-global-check.py" --apply-env || true
fi

printf '\n次の手順:\n'
printf '  mise install\n'
printf '  "$(mise which python3)" -m pip install -r %s/requirements.txt\n' "$REPO_ROOT"
printf '  git submodule update --init packages/extras/_active\n'
printf '  ./scripts/bootstrap.sh\n'
printf '  pi を起動して /mcp でOAuth接続を確認\n'

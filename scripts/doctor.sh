#!/usr/bin/env bash
# harunon-slim のインストール状態と各ランタイムの健全性を診断する。
#
#   scripts/doctor.sh [TARGET] [--dest DIR]
#
# チェック内容:
#   1. 前提ツール (jq, rsync, node, python3) の確認
#   2. 各ターゲットのインストール状況（ledger の有無、managedPaths の配置）
#   3. 配布物とローカル環境のドリフト（差分）確認
#   4. 各 AI ランタイム CLI の PATH 上の確認
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_NAME="install-manifest.json"
LEGACY_LEDGER_NAME=".harunon-pi-agent-slim.installed.json"

TARGET=""
DEST_OVERRIDE=""

usage() {
  echo "Usage: $0 [TARGET] [--dest DIR]"
  echo "  TARGET     payload directory name (checks all available targets if omitted)"
  echo "  --dest     override destination directory for the target"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dest)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      DEST_OVERRIDE="$1"
      ;;
    --help|-h) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *)
      [ -z "$TARGET" ] || { usage >&2; exit 2; }
      TARGET="$1"
      ;;
  esac
  shift
done

list_targets() {
  local dir
  for dir in "$REPO_ROOT"/*/; do
    [ -f "$dir/$MANIFEST_NAME" ] && basename "$dir"
  done
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  harunon-slim doctor: 環境診断"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- 1. 前提ツールの確認 -------------------------------------------------------
echo ""
echo "▼ 前提ツール:"
prereq_missing=0

check_cmd() {
  local cmd="$1" required="$2" note="$3"
  if command -v "$cmd" >/dev/null 2>&1; then
    local path
    path="$(command -v "$cmd")"
    printf '  ✓ %-10s : %s\n' "$cmd" "$path"
  else
    if [ "$required" = "required" ]; then
      printf '  ✗ %-10s : 未インストール (必須: %s)\n' "$cmd" "$note"
      prereq_missing=1
    else
      printf '  ⚠ %-10s : 未インストール (推奨: %s)\n' "$cmd" "$note"
    fi
  fi
}

check_cmd "jq" "required" "install.sh / 設定マージに必要"
check_cmd "rsync" "required" "payload 配布に必要"
check_cmd "node" "optional" "hook-runner / JS 拡張の実行に必要"
check_cmd "python3" "optional" "policy 判定 / validate に必要"

# --- 2. 診断対象ターゲットの決定 -----------------------------------------------
targets=()
if [ -f "$REPO_ROOT/$MANIFEST_NAME" ]; then
  # 単一 payload repo (pi-agent-slim 等)
  targets=("root")
elif [ -n "$TARGET" ]; then
  if [ ! -f "$REPO_ROOT/$TARGET/$MANIFEST_NAME" ]; then
    echo "エラー: 不明なターゲット '$TARGET'" >&2
    echo "利用可能なターゲット:" >&2
    while IFS= read -r name; do echo "  $name" >&2; done < <(list_targets)
    exit 2
  fi
  targets=("$TARGET")
else
  while IFS= read -r name; do
    [ -n "$name" ] && targets+=("$name")
  done < <(list_targets)
fi

# --- 3. ターゲットごとの状態診断 -----------------------------------------------
echo ""
echo "▼ ターゲット診断:"

resolve_dest() {
  local manifest="$1"
  if [ -n "$DEST_OVERRIDE" ]; then
    printf '%s' "$DEST_OVERRIDE"
    return 0
  fi
  local config_dir_env config_dir tilde
  config_dir_env="$(jq -r '.configDirEnv // empty' "$manifest")"
  if [ -n "$config_dir_env" ] && [ -n "${!config_dir_env:-}" ]; then
    printf '%s' "${!config_dir_env}"
    return 0
  fi
  config_dir="$(jq -r '.configDir' "$manifest")"
  tilde='~'
  case "$config_dir" in
    "$tilde") printf '%s' "$HOME" ;;
    "$tilde/"*) printf '%s' "$HOME/${config_dir#*/}" ;;
    *) printf '%s' "$config_dir" ;;
  esac
}

cli_map() {
  case "$1" in
    claude) echo "claude" ;;
    codex) echo "codex" ;;
    opencode) echo "opencode" ;;
    pi) echo "pi" ;;
    omp) echo "omp" ;;
    *) echo "" ;;
  esac
}

for t in "${targets[@]}"; do
  manifest=""
  if [ "$t" = "root" ]; then
    manifest="$REPO_ROOT/$MANIFEST_NAME"
    display_name="single-payload (pi)"
  else
    manifest="$REPO_ROOT/$t/$MANIFEST_NAME"
    display_name="$t"
  fi

  dest="$(resolve_dest "$manifest")"
  ledger_name="$(jq -r '.ledger' "$manifest")"
  ledger="$dest/$ledger_name"
  legacy_ledger="$dest/$LEGACY_LEDGER_NAME"

  printf '\n[%s] -> %s\n' "$display_name" "$dest"

  # ランタイム本体の CLI 確認
  cli="$(cli_map "$t")"
  if [ -n "$cli" ]; then
    if command -v "$cli" >/dev/null 2>&1; then
      printf '  ✓ CLI (%s)  : %s\n' "$cli" "$(command -v "$cli")"
    else
      printf '  - CLI (%s)  : PATH に見つかりません（まだインストールされていないか別名です）\n' "$cli"
    fi
  fi

  # インストール状態確認
  if [ ! -d "$dest" ]; then
    printf '  - 状態       : 未インストール (ディレクトリが存在しません)\n'
    continue
  fi

  active_ledger=""
  [ -f "$ledger" ] && active_ledger="$ledger"
  [ -z "$active_ledger" ] && [ -f "$legacy_ledger" ] && active_ledger="$legacy_ledger"

  if [ -z "$active_ledger" ]; then
    printf '  ⚠ 状態       : 未配布 (ディレクトリは存在しますが ledger がありません)\n'
    printf '                 → インストールするには: scripts/install.sh %s\n' "${t#root}"
    continue
  fi

  file_count="$(jq -r '.files // [] | length' "$active_ledger")"
  printf '  ✓ インストール: 配布済み (管理ファイル: %s 件)\n' "$file_count"

  # ドリフト検査
  drift_output=""
  set +e
  if [ "$t" = "root" ]; then
    drift_output="$("$REPO_ROOT/scripts/install.sh" --check 2>&1)"
    drift_rc=$?
  else
    drift_output="$("$REPO_ROOT/scripts/install.sh" "$t" --check 2>&1)"
    drift_rc=$?
  fi
  set -e

  if [ "$drift_rc" -eq 0 ]; then
    printf '  ✓ ドリフト   : なし (配布物と完全一致)\n'
  else
    printf '  ⚠ ドリフト   : 検出（ローカルまたは payload 側に差分あり）\n'
    echo "$drift_output" | sed 's/^/      /'
    printf '                 → 再配布して同期するには: scripts/install.sh %s\n' "${t#root}"
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$prereq_missing" -eq 1 ]; then
  echo "診断結果: 必須ツールが不足しています。上記を確認してインストールしてください。"
  exit 1
else
  echo "診断完了: 前提ツールはすべて利用可能です。"
  exit 0
fi

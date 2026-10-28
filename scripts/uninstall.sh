#!/usr/bin/env bash
# 配布された payload をランタイムの設定ディレクトリから安全にアンインストールする。
#
#   scripts/uninstall.sh [TARGET] [--dry-run] [--dest DIR] [--keep-backups]
#
# payload の場所と管理ファイルは ledger と install-manifest.json から解決する:
#   - ledger に記録された配布済みファイルを削除
#   - 空になった管理ディレクトリをクリーンアップ
#   - バックアップが存在する場合は最新バックアップの場所を案内
#   - ledger を削除
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_NAME="install-manifest.json"
BACKUP_ROOT=".harunon-slim.backups"
LEGACY_LEDGER_NAME=".harunon-pi-agent-slim.installed.json"

TARGET=""
DEST=""
DRY_RUN=0
KEEP_BACKUPS=0

usage() {
  echo "Usage: $0 [TARGET] [--dry-run] [--dest DIR] [--keep-backups]"
  echo "  TARGET          payload directory name (required unless this repo is a single payload)"
  echo "  --dry-run       show what would be removed (no writes or deletions)"
  echo "  --dest          destination directory (default: configDir in $MANIFEST_NAME)"
  echo "  --keep-backups  do not delete the $BACKUP_ROOT directory"
}

list_targets() {
  local dir
  for dir in "$REPO_ROOT"/*/; do
    [ -f "$dir/$MANIFEST_NAME" ] && basename "$dir"
  done
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --keep-backups) KEEP_BACKUPS=1 ;;
    --dest)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      DEST="$1"
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

command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }

# --- payload の解決 ------------------------------------------------------------

if [ -f "$REPO_ROOT/$MANIFEST_NAME" ]; then
  if [ -n "$TARGET" ]; then
    echo "this repo is a single payload; do not pass TARGET" >&2
    exit 2
  fi
  PAYLOAD="$REPO_ROOT"
else
  if [ -z "$TARGET" ] || [ ! -f "$REPO_ROOT/$TARGET/$MANIFEST_NAME" ]; then
    [ -z "$TARGET" ] || echo "unknown target: $TARGET" >&2
    echo "available targets:" >&2
    while IFS= read -r name; do echo "  $name" >&2; done < <(list_targets)
    exit 2
  fi
  PAYLOAD="$REPO_ROOT/$TARGET"
fi
MANIFEST="$PAYLOAD/$MANIFEST_NAME"

ledger_name="$(jq -r '.ledger' "$MANIFEST")"
if [ -z "$DEST" ]; then
  config_dir_env="$(jq -r '.configDirEnv // empty' "$MANIFEST")"
  if [ -n "$config_dir_env" ] && [ -n "${!config_dir_env:-}" ]; then
    DEST="${!config_dir_env}"
  else
    config_dir="$(jq -r '.configDir' "$MANIFEST")"
    tilde='~'
    case "$config_dir" in
      "$tilde") DEST="$HOME" ;;
      "$tilde/"*) DEST="$HOME/${config_dir#*/}" ;;
      *) DEST="$config_dir" ;;
    esac
  fi
fi

ledger="$DEST/$ledger_name"
legacy_ledger="$DEST/$LEGACY_LEDGER_NAME"

if [ ! -d "$DEST" ]; then
  echo "destination directory does not exist: $DEST"
  exit 0
fi

# ledger の特定
active_ledger=""
if [ -f "$ledger" ]; then
  active_ledger="$ledger"
elif [ -f "$legacy_ledger" ]; then
  active_ledger="$legacy_ledger"
fi

if [ -z "$active_ledger" ]; then
  echo "no ledger found in $DEST (target does not seem to be installed by harunon-slim)"
  exit 0
fi

validate_ledger_path() {
  local rel="$1" part rest current root resolved
  case "$rel" in
    ""|/*|*/|*//*|.|..|./*|../*|*/./*|*/../*|*/.|*/..)
      echo "unsafe ledger path: $rel" >&2; return 1 ;;
  esac
  [ -d "$DEST" ] || return 0
  root="$(cd -P "$DEST" && pwd)"
  current="$DEST"
  rest="$rel"
  while [[ "$rest" == */* ]]; do
    part="${rest%%/*}"
    rest="${rest#*/}"
    current="$current/$part"
    if [ -L "$current" ]; then
      resolved="$(cd -P "$current" && pwd)" || { echo "unsafe ledger path: $rel" >&2; return 1; }
      case "$resolved/" in "$root/"*) ;; *) echo "unsafe ledger path: $rel" >&2; return 1 ;; esac
    fi
  done
}

# 配布されたファイルの一覧取得
jq -e 'type == "object" and (.files | type == "array" and all(.[]; type == "string" and length > 0 and (contains("\n") | not) and (contains("\u0000") | not)))' "$active_ledger" >/dev/null || { echo "invalid ledger: $active_ledger" >&2; exit 1; }
installed_list="$(jq -r '.files[]' "$active_ledger")"
installed_files=()
if [ -n "$installed_list" ]; then
  while IFS= read -r f; do
    validate_ledger_path "$f"
    installed_files+=("$f")
  done <<< "$installed_list"
elif jq -e '.files | length > 0' "$active_ledger" >/dev/null; then
  echo "unsafe ledger path: empty" >&2
  exit 1
fi

for rel in ${installed_files[@]+"${installed_files[@]}"}; do
  validate_ledger_path "$rel"
done

echo "target: ${TARGET:-single-payload} -> $DEST"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "dry-run: the following installed files would be removed:"
  for rel in ${installed_files[@]+"${installed_files[@]}"}; do
    if [ -f "$DEST/$rel" ]; then
      echo "  D $rel"
    fi
  done
  echo "  D $(basename "$active_ledger")"
  exit 0
fi

# 実際のファイル削除
removed_count=0
for rel in ${installed_files[@]+"${installed_files[@]}"}; do
  target_file="$DEST/$rel"
  if [ -f "$target_file" ] || [ -L "$target_file" ]; then
    rm -f "$target_file"
    removed_count=$((removed_count + 1))
    # 親ディレクトリが空なら削除（DEST 直下までは削除しない）
    parent="$(dirname "$target_file")"
    while [ "$parent" != "$DEST" ] && [ "$parent" != "." ] && [ -d "$parent" ]; do
      rmdir "$parent" 2>/dev/null || break
      parent="$(dirname "$parent")"
    done
  fi
done

# ledger の削除
rm -f "$active_ledger"
[ -f "$legacy_ledger" ] && rm -f "$legacy_ledger"

echo "uninstalled: removed $removed_count installed files from $DEST"

# バックアップディレクトリの確認と案内
backup_dir="$DEST/$BACKUP_ROOT"
if [ -d "$backup_dir" ]; then
  if [ "$KEEP_BACKUPS" -eq 1 ]; then
    echo "backups preserved in: $backup_dir"
  else
    latest_backup="$(find "$backup_dir" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
    if [ -n "$latest_backup" ]; then
      echo "note: backup of files modified during install remains at:"
      echo "  $latest_backup"
      echo "  (to restore: cp -rp $latest_backup/* $DEST/)"
    fi
  fi
fi

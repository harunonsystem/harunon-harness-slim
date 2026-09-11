#!/usr/bin/env bash
# harunon-pi-agent-slim を pi の設定ディレクトリ（既定 ~/.pi/agent）へ配布する。
#
# 何を配るかは install-manifest.json（build-public-slim.py が harness の pi target 宣言から
# 生成）が持つ。この script は管理パス一覧を直書きしない。
#   managedPaths : rsync で配る相対パス（既存の未管理ファイルは触らない）
#   settingsFile : マージ対象の設定ファイル名
#   settingsKeys : 既存 settingsFile へ上書きするキー（それ以外のローカル値は保持）
#
# 配ったファイルは DEST の ledger（LEDGER_NAME）に記録する。次回の install は「前回配ったが
# 今回の payload に無いファイル」だけを消す（それ以外の dest 側ファイルは触らない）。rsync は
# dest 側だけにあるファイルを消さないため、これが無いと退役した extensions/ が pi に読み込まれ
# 続ける。
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/install-manifest.json"
LEDGER_NAME=".harunon-pi-agent-slim.installed.json"
DEST="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
DRY_RUN=0
CHECK_ONLY=0

command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "rsync is required" >&2; exit 1; }
[ -f "$MANIFEST" ] || { echo "install-manifest.json not found: $MANIFEST" >&2; exit 1; }

usage() {
  echo "Usage: $0 [--dry-run | --check] [--dest DIR]"
  echo "  --dry-run  show what would change (no writes at all)"
  echo "  --check    report drift between this repo and DEST (no writes)"
  echo "  --dest     destination directory (default: \$PI_AGENT_DIR or ~/.pi/agent)"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --check) CHECK_ONLY=1 ;;
    --dest)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      DEST="$1"
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

settings_file="$(jq -r '.settingsFile' "$MANIFEST")"
settings_keys_json="$(jq -c '.settingsKeys' "$MANIFEST")"
ledger="$DEST/$LEDGER_NAME"

# bash 3.2: mapfile が無いので while read で配列に積む
managed_paths=()
while IFS= read -r path; do
  [ -n "$path" ] && managed_paths+=("$path")
done < <(jq -r '.managedPaths[]' "$MANIFEST")

# settingsFile は settingsKeys だけをマージするので rsync 対象から外す
sync_paths=()
for path in "${managed_paths[@]}"; do
  [ "$path" = "$settings_file" ] && continue
  [ -e "$REPO_ROOT/$path" ] || { echo "managed path missing in repo: $path" >&2; exit 1; }
  sync_paths+=("$path")
done

# 今回 payload が配るファイル（REPO_ROOT 相対、1 行 1 パス、ソート済み）
payload_files() {
  (cd "$REPO_ROOT" && find "${sync_paths[@]}" -type f | LC_ALL=C sort)
}

# 前回 ledger に記録されたファイル（無ければ空）
ledger_files() {
  [ -f "$ledger" ] || return 0
  jq -r '.files[]' "$ledger"
}

# 前回配ったが今回 payload に無いファイル = prune 対象（dest に実在するものだけ）
stale_files() {
  local candidate
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    [ -f "$DEST/$candidate" ] && printf '%s\n' "$candidate"
  done < <(LC_ALL=C comm -23 <(ledger_files | LC_ALL=C sort -u) <(payload_files))
}

# 既存 settings と repo の settings を settingsKeys だけ突き合わせた結果を stdout に出す
merged_settings() {
  jq -S -s --argjson keys "$settings_keys_json" \
    '.[0] as $local | .[1] as $source
     | reduce $keys[] as $key ($local; if ($source | has($key)) then .[$key] = $source[$key] else . end)' \
    "$DEST/$settings_file" "$REPO_ROOT/$settings_file"
}

# 比較は整形差（tab / 2 space、キー順）を無視して値だけ見る
settings_in_sync() {
  merged_settings | cmp -s - <(jq -S . "$DEST/$settings_file")
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  [ -d "$DEST" ] || { echo "destination does not exist: $DEST" >&2; exit 1; }
  drift=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    echo "$line"
    drift=1
  done < <(cd "$REPO_ROOT" && rsync -aniO --relative "${sync_paths[@]}" "$DEST/")
  while IFS= read -r stale; do
    [ -n "$stale" ] || continue
    echo "D $stale (retired from payload)"
    drift=1
  done < <(stale_files)
  if [ -f "$DEST/$settings_file" ]; then
    if ! settings_in_sync; then
      echo "M $settings_file (managed keys)"
      drift=1
    fi
  else
    echo "A $settings_file"
    drift=1
  fi
  exit "$drift"
fi

# --dry-run はファイルシステムに一切書かない（mkdir も ledger も）。rsync の dry-run は
# 存在しない dest でも動く
[ "$DRY_RUN" -eq 1 ] || mkdir -p "$DEST"
# -O: ディレクトリの mtime は同期も比較もしない（prune で dest 側のディレクトリ時刻だけが
# 変わり、--check が `.d..t.... rules/` を drift として報告してしまう）
rsync_args=(-aO --relative)
[ "$DRY_RUN" -eq 1 ] && rsync_args+=(--dry-run --itemize-changes)
(cd "$REPO_ROOT" && rsync "${rsync_args[@]}" "${sync_paths[@]}" "$DEST/")

while IFS= read -r stale; do
  [ -n "$stale" ] || continue
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "D $stale (retired from payload)"
  else
    rm -f "$DEST/$stale"
    echo "removed retired file: $stale"
  fi
done < <(stale_files)

if [ ! -f "$DEST/$settings_file" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "A $settings_file"
  else
    cp "$REPO_ROOT/$settings_file" "$DEST/$settings_file"
  fi
elif [ "$DRY_RUN" -eq 1 ]; then
  settings_in_sync || echo "M $settings_file (managed keys only)"
else
  if settings_in_sync; then
    : # 管理キーは一致。ローカルの整形を保つため触らない
  else
    tmp_settings="$(mktemp "${TMPDIR:-/tmp}/pi-agent-slim-settings.XXXXXX")"
    trap 'rm -f "$tmp_settings"' EXIT
    merged_settings > "$tmp_settings"
    chmod 600 "$tmp_settings"
    mv "$tmp_settings" "$DEST/$settings_file"
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "pi configuration dry-run: $DEST"
else
  payload_files | jq -R . | jq -s '{files: .}' > "$ledger"
  echo "pi configuration ready: $DEST"
fi

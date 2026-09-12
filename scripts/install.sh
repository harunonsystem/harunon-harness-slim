#!/usr/bin/env bash
# payload をランタイムの設定ディレクトリへ配布する。
#
#   scripts/install.sh [TARGET] [--dry-run | --check] [--dest DIR]
#
# payload の場所は repo の形で決まる:
#   - repo 直下に install-manifest.json がある（単一 payload repo） → repo 全体が payload。TARGET は付けない
#   - 無い（複数 target repo）                                        → <repo>/<TARGET>/ が payload。TARGET 必須
#
# 何を配るかは payload の install-manifest.json が持つ。この script は管理パス一覧を直書きしない。
#   configDir      : 既定の配布先（先頭 ~ は $HOME）。--dest で上書き
#   configDirEnv   : 配布先を指す環境変数名（例 CODEX_HOME）。設定されていれば configDir より優先
#   managedPaths   : rsync で配る相対パス（既存の未管理ファイルは触らない）
#   settingsFile   : 設定ファイル名（null なら設定の同期は無い）
#   settingsFormat : json なら settingsKeys だけを既存ファイルへマージ。toml / yaml は
#                    dest に無いときだけ置き、あれば触らない（同期対象キーは README に列挙）
#   settingsKeys   : json マージで上書きする dotted path（それ以外のローカル値は保持）
#   ledger         : dest に置く配布記録のファイル名
#
# 配ったファイルは dest の ledger に記録する。次回の install は「前回配ったが今回の payload に
# 無いファイル」だけを消す（それ以外の dest 側ファイルは触らない）。rsync は dest 側だけにある
# ファイルを消さないため、これが無いと退役した extensions/ がランタイムに読み込まれ続ける。
#
# 上書き・削除の前に元ファイルを dest の BACKUP_ROOT/<timestamp>/ へ退避する（利用者が手で
# 編集していた CLAUDE.md 等が初回 install で消えないように）。何も退避しなければディレクトリは残さない。
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_NAME="install-manifest.json"
BACKUP_ROOT=".harunon-slim.backups"
# pi 単体配布の旧 ledger 名。新 ledger が無いときだけ前回分として読む
LEGACY_LEDGER_NAME=".harunon-pi-agent-slim.installed.json"

TARGET=""
DEST=""
DRY_RUN=0
CHECK_ONLY=0

usage() {
  echo "Usage: $0 [TARGET] [--dry-run | --check] [--dest DIR]"
  echo "  TARGET     payload directory name (required unless this repo is a single payload)"
  echo "  --dry-run  show what would change (no writes at all)"
  echo "  --check    report drift between the payload and DEST (no writes)"
  echo "  --dest     destination directory (default: configDir in $MANIFEST_NAME)"
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
    --check) CHECK_ONLY=1 ;;
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
command -v rsync >/dev/null 2>&1 || { echo "rsync is required" >&2; exit 1; }

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

settings_file="$(jq -r '.settingsFile // empty' "$MANIFEST")"
settings_format="$(jq -r '.settingsFormat // empty' "$MANIFEST")"
settings_keys_json="$(jq -c '.settingsKeys // []' "$MANIFEST")"
ledger_name="$(jq -r '.ledger' "$MANIFEST")"
if [ -z "$DEST" ]; then
  config_dir_env="$(jq -r '.configDirEnv // empty' "$MANIFEST")"
  if [ -n "$config_dir_env" ] && [ -n "${!config_dir_env:-}" ]; then
    DEST="${!config_dir_env}"
  else
    config_dir="$(jq -r '.configDir' "$MANIFEST")"
    # manifest の "~" は文字列なので shell 展開されない。先頭だけ $HOME に置き換える
    tilde='~'
    case "$config_dir" in
      "$tilde") DEST="$HOME" ;;
      "$tilde/"*) DEST="$HOME/${config_dir#*/}" ;;
      *) DEST="$config_dir" ;;
    esac
  fi
fi
ledger="$DEST/$ledger_name"
# 同一秒内の再実行でも衝突しないよう PID を付ける（前回分の有無で「今回退避したか」を判定する）
backup_dir="$DEST/$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)-$$"

# bash 3.2: mapfile が無いので while read で配列に積む
managed_paths=()
while IFS= read -r path; do
  [ -n "$path" ] && managed_paths+=("$path")
done < <(jq -r '.managedPaths[]' "$MANIFEST")

# settingsFile は settingsKeys だけをマージするので rsync 対象から外す
sync_paths=()
for path in "${managed_paths[@]}"; do
  [ -n "$settings_file" ] && [ "$path" = "$settings_file" ] && continue
  [ -e "$PAYLOAD/$path" ] || { echo "managed path missing in payload: $path" >&2; exit 1; }
  sync_paths+=("$path")
done

# 今回 payload が配るファイル（PAYLOAD 相対、1 行 1 パス、ソート済み）
payload_files() {
  (cd "$PAYLOAD" && find "${sync_paths[@]}" -type f | LC_ALL=C sort)
}

# 前回 ledger に記録されたファイル（無ければ旧名を探し、それも無ければ空）
ledger_files() {
  local source="$ledger"
  [ -f "$source" ] || source="$DEST/$LEGACY_LEDGER_NAME"
  [ -f "$source" ] || return 0
  jq -r '.files[]' "$source"
}

# 前回配ったが今回 payload に無いファイル = prune 対象（dest に実在するものだけ）
stale_files() {
  local candidate
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    [ -f "$DEST/$candidate" ] && printf '%s\n' "$candidate"
  done < <(LC_ALL=C comm -23 <(ledger_files | LC_ALL=C sort -u) <(payload_files))
}

# --- settings ------------------------------------------------------------------

# json: 既存 settings と payload の settings を settingsKeys（dotted path）だけ突き合わせた結果を
# stdout に出す。payload 側に無い path は触らない
merged_settings() {
  jq -S -s --argjson keys "$settings_keys_json" \
    '.[0] as $local | .[1] as $source
     | reduce $keys[] as $key ($local;
         ($key | split(".")) as $path
         | if ($source | getpath($path)) != null then setpath($path; $source | getpath($path)) else . end)' \
    "$DEST/$settings_file" "$PAYLOAD/$settings_file"
}

# 比較は整形差（tab / 2 space、キー順）を無視して値だけ見る
settings_in_sync() {
  merged_settings | cmp -s - <(jq -S . "$DEST/$settings_file")
}

# settings の drift を 1 行で出す（無ければ何も出さない）。json 以外は「dest に無い」だけを drift とする
settings_drift() {
  [ -n "$settings_file" ] || return 0
  if [ ! -f "$DEST/$settings_file" ]; then
    echo "A $settings_file"
  elif [ "$settings_format" = "json" ]; then
    settings_in_sync || echo "M $settings_file (managed keys)"
  fi
}

# settings を dest に反映する（書き込みあり）
apply_settings() {
  [ -n "$settings_file" ] || return 0
  if [ ! -f "$DEST/$settings_file" ]; then
    cp "$PAYLOAD/$settings_file" "$DEST/$settings_file"
    return 0
  fi
  if [ "$settings_format" != "json" ]; then
    echo "S $settings_file (not merged: $settings_format; apply settingsKeys from $MANIFEST_NAME by hand)"
    return 0
  fi
  settings_in_sync && return 0 # 管理キーは一致。ローカルの整形を保つため触らない
  local tmp_settings
  tmp_settings="$(mktemp "${TMPDIR:-/tmp}/slim-install-settings.XXXXXX")"
  merged_settings > "$tmp_settings"
  chmod 600 "$tmp_settings"
  back_up "$settings_file"
  mv "$tmp_settings" "$DEST/$settings_file"
}

# dest の既存ファイルを backup_dir へ同じ相対パスで退避する（書き込みあり）
back_up() {
  local rel="$1"
  mkdir -p "$backup_dir/$(dirname "$rel")"
  cp -p "$DEST/$rel" "$backup_dir/$rel"
}

# --- check ---------------------------------------------------------------------

# 比較は内容（checksum）で行い、mtime は同期も比較もしない。git clone は mtime を復元しないので
# mtime 比較だと clone 直後は全ファイルが差分になり、内容が同じファイルまで転送・退避される
rsync_base=(-rlpgoD --checksum --relative)

# 内容・パーミッションの差だけを itemize する。mtime を同期しないため rsync は内容が同じ
# ファイルにも `.f..T....`（時刻だけ転送時刻になる）を出すので、その行は落とす
itemized_changes() {
  (cd "$PAYLOAD" && rsync "${rsync_base[@]}" --dry-run --itemize-changes "${sync_paths[@]}" "$DEST/") \
    | { grep -v -E '^\.f\.\.T\.{4} ' || true; }
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  [ -d "$DEST" ] || { echo "destination does not exist: $DEST" >&2; exit 1; }
  drift=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    echo "$line"
    drift=1
  done < <(itemized_changes)
  while IFS= read -r stale; do
    [ -n "$stale" ] || continue
    echo "D $stale (retired from payload)"
    drift=1
  done < <(stale_files)
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    echo "$line"
    drift=1
  done < <(settings_drift)
  exit "$drift"
fi

# --- install / dry-run ---------------------------------------------------------

# --dry-run はファイルシステムに一切書かない（mkdir も ledger も）。rsync の dry-run は
# 存在しない dest でも動く
[ "$DRY_RUN" -eq 1 ] || mkdir -p "$DEST"
if [ "$DRY_RUN" -eq 1 ]; then
  itemized_changes
else
  # 上書きされる既存ファイルは backup_dir へ（rsync は退避対象があるときだけディレクトリを作る）
  (cd "$PAYLOAD" && rsync "${rsync_base[@]}" --backup --backup-dir="$backup_dir" "${sync_paths[@]}" "$DEST/")
fi

while IFS= read -r stale; do
  [ -n "$stale" ] || continue
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "D $stale (retired from payload)"
  else
    back_up "$stale"
    rm -f "$DEST/$stale"
    echo "removed retired file: $stale"
  fi
done < <(stale_files)

if [ "$DRY_RUN" -eq 1 ]; then
  settings_drift
  echo "dry-run: $DEST"
else
  apply_settings
  # ledger は途中で止まっても壊れないよう別名に書いてから置き換える
  payload_files | jq -R . | jq -s '{files: .}' > "$ledger.tmp"
  mv "$ledger.tmp" "$ledger"
  if [ -d "$backup_dir" ]; then
    echo "backed up replaced files: $backup_dir"
  fi
  echo "installed: $DEST"
fi

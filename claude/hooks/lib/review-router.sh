#!/bin/bash
# 共有ライブラリ: レビュー経路の機械分類器
#
# 提供する関数:
#   review_route <numstat_total> [commit_subjects]
#     — stdin に `git diff --name-status` 形式のファイル一覧を渡し、
#       route を1語 echo する: none | bypass | difit | review
#     numstat_total: 追加+削除行数の合計（difit 判定の閾値に使用）
#     commit_subjects: コミット件名の改行区切りリスト（省略可、revert 一括判定用）
#
# 分類優先順位: none > bypass > difit > review
#   none    — 全ファイルが *.md/*.mdx/*.txt（拡張子判定。ディレクトリは見ない）
#   bypass  — 全ファイルが lockfile/snapshot/生成物、または全コミット件名が Revert
#   difit   — 変更ファイル数 >= 10、変更行数 >= 400、または components/・
#             designsystems/ 配下を含む
#   review  — それ以外（code+docs 混合や空 diff もここに落ちる）
#
# パターン定義は本ファイル先頭に1箇所で契約文字列として集約する（core-standards.md
# 「散在するハードコード契約文字列」禁止に対応）。bash 3.2（macOS 標準）互換。

# --- 分類パターン定数 ---
_ROUTER_DOC_EXT_RE='\.(md|mdx|txt)$'
_ROUTER_LOCKFILE_BASENAMES="pnpm-lock.yaml package-lock.json yarn.lock Gemfile.lock Cargo.lock"
_ROUTER_SNAPSHOT_DIR_RE='(^|/)__snapshots__/'
_ROUTER_SNAPSHOT_EXT_RE='\.snap$'
_ROUTER_GENERATED_DIR_RE='(^|/)generated/'
_ROUTER_DIFIT_DIR_RE='(^|/)(components|designsystems)/'
_ROUTER_DIFIT_FILE_THRESHOLD=10
_ROUTER_DIFIT_LINE_THRESHOLD=400
_ROUTER_REVERT_SUBJECT_RE='^Revert '

# path が doc 分類か判定する。ディレクトリではなく拡張子で判定する
# （docs/ 配下のコードファイルがレビューなしで通る穴を作らない。
#  SSOT codex-review-policy.md の免除対象は「Markdown のみ」）。
_router_is_doc_file() {
  echo "$1" | grep -qE "$_ROUTER_DOC_EXT_RE"
}

# path が bypass 分類（lockfile / snapshot / 生成物）か判定する。
_router_is_bypass_file() {
  local path="$1" base lockfile
  base=$(basename "$path")
  for lockfile in $_ROUTER_LOCKFILE_BASENAMES; do
    [ "$base" = "$lockfile" ] && return 0
  done
  echo "$path" | grep -qE "$_ROUTER_SNAPSHOT_DIR_RE" && return 0
  echo "$path" | grep -qE "$_ROUTER_SNAPSHOT_EXT_RE" && return 0
  echo "$path" | grep -qE "$_ROUTER_GENERATED_DIR_RE" && return 0
  return 1
}

# path が difit 判定対象ディレクトリ（components/・designsystems/ 配下）か判定する。
_router_is_difit_dir_file() {
  echo "$1" | grep -qE "$_ROUTER_DIFIT_DIR_RE"
}

# fn を全 path に適用し、全て true なら 0 を返す（空リストは呼び出し元で別途処理する）。
_router_all_match() {
  local fn="$1" p
  shift
  for p in "$@"; do
    "$fn" "$p" || return 1
  done
  return 0
}

# fn がいずれかの path で true なら 0 を返す。
_router_any_match() {
  local fn="$1" p
  shift
  for p in "$@"; do
    "$fn" "$p" && return 0
  done
  return 1
}

# subjects（改行区切り）の全行が Revert コミット件名か判定する。
_router_all_revert_subjects() {
  local subjects="$1" line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    echo "$line" | grep -qE "$_ROUTER_REVERT_SUBJECT_RE" || return 1
  done <<REVERT_SUBJECTS
$subjects
REVERT_SUBJECTS
  return 0
}

review_route() {
  local numstat_total="${1:-0}"
  local commit_subjects="${2:-}"
  local line path
  local -a paths=()

  # `|| [ -n "$line" ]` で末尾に改行のない入力でも最終行を読み落とさない
  # （command substitution が末尾改行を除去した文字列をそのまま渡す呼び出し元がある）。
  while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    # git diff --name-status: "M\tpath" / rename・copy は "R100\told\tnew"（最終列が新パス）
    path=$(printf '%s' "$line" | awk -F'\t' '{print $NF}')
    [ -z "$path" ] && continue
    paths+=("$path")
  done

  local file_count=${#paths[@]}

  # 空 diff は安全側（review）に倒す。none 判定の "全ファイルが doc" は
  # 空リストで vacuously true になるため、ここで明示的に弾く。
  if [ "$file_count" -eq 0 ]; then
    echo "review"
    return
  fi

  if _router_all_match _router_is_doc_file "${paths[@]}"; then
    echo "none"
    return
  fi

  if _router_all_match _router_is_bypass_file "${paths[@]}"; then
    echo "bypass"
    return
  fi

  if [ -n "$commit_subjects" ] && _router_all_revert_subjects "$commit_subjects"; then
    echo "bypass"
    return
  fi

  if [ "$file_count" -ge "$_ROUTER_DIFIT_FILE_THRESHOLD" ] \
    || [ "$numstat_total" -ge "$_ROUTER_DIFIT_LINE_THRESHOLD" ] \
    || _router_any_match _router_is_difit_dir_file "${paths[@]}"; then
    echo "difit"
    return
  fi

  echo "review"
}

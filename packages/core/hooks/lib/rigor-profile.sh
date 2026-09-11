#!/bin/bash
# 共有ライブラリ: rigor profile 判定 (ADR-009)
#
# 提供する関数:
#   rigor_profile [repo_root]
#     — "casual" か "rigorous" を1語 echo する
#
# 判定順（first match wins）:
#   (1) RIGOR_PATTERNS_FILE の pattern に repo_root がマッチ → その profile
#   (2) RIGOR_LOCAL_FILE の defaultProfile
#   (3) "rigorous"（fail-safe。未設定時は既存の全ゲート有効な挙動を維持）
#
# repo_root 省略時は `git rev-parse --show-toplevel` で解決する。git repo 外
# （解決できない）場合は (1) をスキップし (2) から判定する。
#
# ファイル不在・jq 不在・壊れた JSON・未知の profile 値はすべて次のステップに
# フォールバックし、最終的に "rigorous" に倒す（gate の fail-safe）。
# stderr 警告は「壊れた JSON」の場合のみ出す。
#
# パターン定義は本ファイル先頭に1箇所で契約文字列として集約する（core-standards.md
# 「散在するハードコード契約文字列」禁止に対応）。bash 3.2（macOS 標準）互換。

# --- 設定ファイルパス（テスト注入点） ---
: "${RIGOR_PATTERNS_FILE:=$HOME/.claude/rigor-patterns.json}"
: "${RIGOR_LOCAL_FILE:=$HOME/.claude/rigor.local.json}"

_RIGOR_DEFAULT_PROFILE="rigorous"

# profile 値が既知のものか判定する。
_rigor_is_valid_profile() {
  case "$1" in
    casual|rigorous) return 0 ;;
    *) return 1 ;;
  esac
}

# git repo のルートパスを取得する。repo 外では空文字を返す。
_rigor_repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || echo ""
}

# JSON ファイルを読み、jq で valid か検証した上で本文を echo する。
# 不在・jq 不在・壊れた JSON では空文字を返す（壊れた JSON のみ stderr 警告）。
_rigor_read_valid_json() {
  local file="$1"
  [ -f "$file" ] || { echo ""; return; }
  command -v jq > /dev/null 2>&1 || { echo ""; return; }

  local json
  json=$(cat "$file" 2>/dev/null)
  if ! echo "$json" | jq -e . > /dev/null 2>&1; then
    echo "rigor_profile: 壊れた JSON をスキップします: $file" >&2
    echo ""
    return
  fi
  echo "$json"
}

# RIGOR_PATTERNS_FILE を first-match-wins で評価し、マッチした profile を返す。
# pattern はローカル repo root または git remote の owner/repo に対する glob。
# repo_root が空、ファイル不在・jq 不在・壊れた JSON、マッチ無しでは空文字を返す。
_rigor_patterns_profile() {
  local repo_root="$1"
  [ -z "$repo_root" ] && { echo ""; return; }

  local json
  json=$(_rigor_read_valid_json "$RIGOR_PATTERNS_FILE")
  [ -z "$json" ] && { echo ""; return; }

  local count i pattern profile remote_repo
  count=$(echo "$json" | jq 'length' 2>/dev/null)
  [ -z "$count" ] && { echo ""; return; }

  remote_repo=$(git -C "$repo_root" remote get-url origin 2>/dev/null \
    | perl -ne 'chomp; s#\.git$##; s#^.*github\.com[:/]##; print' || true)

  i=0
  while [ "$i" -lt "$count" ]; do
    pattern=$(echo "$json" | jq -r ".[$i].pattern // empty" 2>/dev/null)
    profile=$(echo "$json" | jq -r ".[$i].profile // empty" 2>/dev/null)
    if [ -n "$pattern" ]; then
      # SC2254: pattern はユーザー定義の glob（例 "*/harunon-harness"）として
      # 意図的に unquoted で展開する。リテラル一致に倒すと glob 機能が失われる。
      # shellcheck disable=SC2254
      case "$repo_root" in
        $pattern)
          echo "$profile"
          return
          ;;
      esac
      # shellcheck disable=SC2254
      case "$remote_repo" in
        $pattern)
          echo "$profile"
          return
          ;;
      esac
    fi
    i=$((i + 1))
  done
  echo ""
}

# RIGOR_LOCAL_FILE の defaultProfile を返す。
# ファイル不在・jq 不在・壊れた JSON・キー無しでは空文字を返す。
_rigor_local_default_profile() {
  local json
  json=$(_rigor_read_valid_json "$RIGOR_LOCAL_FILE")
  [ -z "$json" ] && { echo ""; return; }
  echo "$json" | jq -r '.defaultProfile // empty' 2>/dev/null
}

rigor_profile() {
  local repo_root="${1:-}"
  local profile

  [ -z "$repo_root" ] && repo_root=$(_rigor_repo_root)

  profile=$(_rigor_patterns_profile "$repo_root")
  if _rigor_is_valid_profile "$profile"; then
    echo "$profile"
    return
  fi

  profile=$(_rigor_local_default_profile)
  if _rigor_is_valid_profile "$profile"; then
    echo "$profile"
    return
  fi

  echo "$_RIGOR_DEFAULT_PROFILE"
}

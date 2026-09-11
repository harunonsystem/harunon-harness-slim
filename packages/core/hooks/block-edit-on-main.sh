#!/bin/bash
# PreToolUse:Edit,Write — main ブランチでのファイル編集をブロック
set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"

# casual profile では main ブランチ直編集ガードを課さない（ADR-009）。
[ "$(rigor_profile)" = "casual" ] && exit 0

# harness の SSOT checkout かどうかを構造で判定する（配布宣言 + distribute 本体）。
# ディレクトリ名で判定すると clone 先の名前や slim 生成物（harunon-harness-slim）で
# main 直編集が deny される（2026-09-11 に slim の CI で実測）。
_is_harness_checkout() {
  [ -d "$1/packages/targets" ] && [ -f "$1/scripts/distribute.py" ]
}

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')

# Edit/Write 以外はスルー（pi の apply_patch は bridge が Write としてここに届ける）
case "$TOOL_NAME" in
  Edit|Write) ;;
  *) exit 0 ;;
esac

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
HOOK_CWD=$(echo "$INPUT" | jq -r '.cwd // ""')
: "${HOOK_CWD:=$PWD}"

# gwm の worktree_base_path を取得（全候補パスの判定で共有する）
GWM_BASE=""
if [ -f "$HOME/.config/gwm/config.toml" ]; then
  GWM_BASE=$(perl -ne 'if (/^\s*worktree_base_path\s*=\s*"([^"]*)"/) { print "$1\n"; exit }' \
    "$HOME/.config/gwm/config.toml")
fi
GWM_BASE="${GWM_BASE/#\~/$HOME}"
: "${GWM_BASE:=$HOME/projects/worktrees}"
REAL_GWM_BASE=$(realpath "$GWM_BASE" 2>/dev/null || echo "")

# main/master 直編集と判定した候補の情報（deny メッセージ用）
BLOCKED_REPO=""
BLOCKED_BRANCH=""
BLOCKED_PATH=""

# 絶対パス候補を「存在する最深の祖先まで dirname で遡って realpath で解決し、
# 存在しない残り suffix をそのまま連結する」形で正規化する。macOS の realpath は
# 存在しないパスの正規化（-m）に対応しないための代替実装（bash 3.2 互換）。
# tmp / .claude / gwm バイパスを「実際に指す場所」で判定するために使う
# （2026-08-14 Codex review P1: `/tmp/../<repo>/file` のような traversal で
# 字面だけ見ると本来 main ガード対象のパスが tmp/.claude バイパスをすり抜けていた）。
canonicalize_path() {
  local input="$1"
  local suffix=""
  local dir="$input"
  local resolved=""

  while [ -n "$dir" ]; do
    if [ -e "$dir" ]; then
      resolved=$(realpath "$dir" 2>/dev/null || echo "$dir")
      break
    fi
    if [ -n "$suffix" ]; then
      suffix="$(basename "$dir")/$suffix"
    else
      suffix="$(basename "$dir")"
    fi
    dir=$(dirname "$dir")
  done
  : "${resolved:=/}"

  if [ -n "$suffix" ]; then
    printf '%s/%s' "$resolved" "$suffix"
  else
    printf '%s' "$resolved"
  fi
}

# canonicalize 後もパスに `..` セグメントが残っているか判定する。存在しない中間
# ディレクトリ越しの `..`（例: /tmp/does-not-exist/../etc/passwd）は realpath でも
# 解決できず literal な `..` が残る。この場合は「どこを指すか確定できない」ため、
# tmp / .claude / gwm のいずれのバイパスも適用してはならない。
path_has_unresolved_dotdot() {
  case "$1" in
    ..|../*|*/../*|*/..) return 0 ;;
    *) return 1 ;;
  esac
}

# 1 候補パスを判定する。ブロック対象なら 1、スルーしてよいなら 0 を返す。
check_candidate_path() {
  local candidate="$1"
  [ -z "$candidate" ] && return 0

  local canonical
  canonical=$(canonicalize_path "$candidate")

  if ! path_has_unresolved_dotdot "$canonical"; then
    # /tmp/ や /private/tmp/ 配下はスルー（scratch ファイルはガード対象外）。
    # CLAUDE_HOOK_ALLOW_TMP_PATHS を設定するとこのバイパスを無効化する（テスト注入点。
    # TMPDIR が /tmp 配下の CI 等で fixture が誤ってバイパスされるのを防ぐ。既定は未設定＝従来どおりスルー）。
    if [ -z "${CLAUDE_HOOK_ALLOW_TMP_PATHS:-}" ]; then
      case "$canonical" in
        /tmp/*|/private/tmp/*) return 0 ;;
      esac
    fi

    # gwm worktree 配下はスルー
    if [ -n "$REAL_GWM_BASE" ]; then
      case "$canonical" in
        "$REAL_GWM_BASE"/*) return 0 ;;
      esac
    fi

    # .claude/ 配下の設定ファイルはスルー
    case "$canonical" in
      */.claude/*|*/.claude) return 0 ;;
    esac
  fi

  # git リポジトリを特定（ディレクトリならそのまま、ファイルが存在しなければ親ディレクトリで探す）
  local search_dir
  if [ -d "$canonical" ]; then
    search_dir="$canonical"
  elif [ -e "$canonical" ]; then
    search_dir=$(dirname "$canonical")
  else
    search_dir=$(dirname "$canonical")
    while [ -n "$search_dir" ] && [ "$search_dir" != "/" ] && [ ! -d "$search_dir" ]; do
      search_dir=$(dirname "$search_dir")
    done
  fi

  # git リポジトリ外はスルー
  local git_root
  git_root=$(git -C "$search_dir" rev-parse --show-toplevel 2>/dev/null || echo "")
  [ -z "$git_root" ] && return 0

  # harness リポジトリ自体はスルー（main で作業する運用）
  local repo_name
  repo_name=$(basename "$git_root")
  _is_harness_checkout "$git_root" && return 0

  # harness の submodule（packages/extras/_active 等）も同じ main 直運用（SSOT-first）
  local superproject
  superproject=$(git -C "$git_root" rev-parse --show-superproject-working-tree 2>/dev/null || echo "")
  if [ -n "$superproject" ] && _is_harness_checkout "$superproject"; then
    return 0
  fi

  # 現在のブランチを取得
  local current_branch
  current_branch=$(git -C "$git_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  case "$current_branch" in
    main|master)
      BLOCKED_REPO="$repo_name"
      BLOCKED_BRANCH="$current_branch"
      BLOCKED_PATH="$candidate"
      return 1
      ;;
    *) return 0 ;;
  esac
}

# Codex の apply_patch envelope（`.tool_input.input`）から `*** Add/Update/Delete File:` /
# `*** Move to:` の対象パスを抽出し、HOOK_CWD 基準で絶対パス化して 1 行 1 パスで出力する。
extract_patch_paths() {
  local patch_text
  patch_text=$(echo "$INPUT" | jq -r '.tool_input.input // ""')
  [ -z "$patch_text" ] && return 0

  local line raw
  while IFS= read -r line; do
    case "$line" in
      '*** Add File: '*|'*** Delete File: '*|'*** Update File: '*|'*** Move to: '*)
        raw="${line#*: }"
        case "$raw" in
          /*) printf '%s\n' "$raw" ;;
          *) printf '%s\n' "$HOOK_CWD/$raw" ;;
        esac
        ;;
    esac
  done <<< "$patch_text"
}

# 判定対象の候補パス一覧を組み立てる。
# - file_path があればそれ単体（Edit/Write の通常経路）
# - file_path が空なら apply_patch envelope からパスを抽出
# - envelope からも 1 つも取れなければ、素通りさせず HOOK_CWD 自体をガード対象にする
#   （fail-closed。パスの分からない編集を main 直で許してしまうのを防ぐ）
resolve_candidates() {
  if [ -n "$FILE_PATH" ]; then
    printf '%s\n' "$FILE_PATH"
    return 0
  fi

  local extracted
  extracted=$(extract_patch_paths)
  if [ -n "$extracted" ]; then
    printf '%s\n' "$extracted"
  else
    printf '%s\n' "$HOOK_CWD"
  fi
}

CANDIDATES=$(resolve_candidates)

while IFS= read -r candidate; do
  [ -z "$candidate" ] && continue
  if ! check_candidate_path "$candidate"; then
    cat >&2 <<EOF
[main-branch guard] main ブランチで直接ファイルを編集しようとしています。
worktree を作成してから作業してください:

  gwm add <branch-name>     # 新規 worktree 作成
  gwm list                  # 既存 worktree 一覧

現在のリポジトリ: $BLOCKED_REPO
現在のブランチ: $BLOCKED_BRANCH
対象ファイル: $BLOCKED_PATH
EOF
    exit 2
  fi
done <<< "$CANDIDATES"

exit 0

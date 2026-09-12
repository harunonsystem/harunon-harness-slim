#!/bin/bash
# worktree 作成を gwm に強制する。
# - 外部 path への EnterWorktree / Bash の `git worktree add` / `claude worktree` を block
# - gwm 未インストールやgit repo外でもraw worktree作成はfail-closed
set -euo pipefail

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/rigor-profile.sh
source "$HOOK_DIR/lib/rigor-profile.sh"
# shellcheck source=lib/command-normalize.sh
source "$HOOK_DIR/lib/command-normalize.sh"

# casual profile では gwm 強制ゲートを課さない（ADR-009）。
[ "$(rigor_profile)" = "casual" ] && exit 0

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')

case "$TOOL_NAME" in
  EnterWorktree)
    ENTER_PATH=$(echo "$INPUT" | jq -r '.tool_input.path // ""')

    # name 形式は Claude の WorktreeCreate hook に作成を委譲する新規作成フロー。
    # 明示 path の既存 worktree だけを下の GWM 配下チェックに通す。
    [ -z "$ENTER_PATH" ] && exit 0

    # gwm の worktree_base_path を config から取得
    GWM_BASE=""
    if [ -f "$HOME/.config/gwm/config.toml" ]; then
      GWM_BASE=$(perl -ne 'if (/^\s*worktree_base_path\s*=\s*"([^"]*)"/) { print "$1\n"; exit }' \
        "$HOME/.config/gwm/config.toml")
    fi
    # ~ を $HOME に展開
    GWM_BASE="${GWM_BASE/#\~/$HOME}"
    # フォールバック
    : "${GWM_BASE:=$HOME/projects/worktrees}"

    # gwm 管理下の既存 worktree への移動は許可
    # gwm go は cd をセッション間で保持できないため EnterWorktree が必要
    if [ -n "$ENTER_PATH" ] && [ -d "$ENTER_PATH" ]; then
      REAL_PATH=$(realpath "$ENTER_PATH" 2>/dev/null || echo "")
      REAL_BASE=$(realpath "$GWM_BASE" 2>/dev/null || echo "")
      if [ -n "$REAL_PATH" ] && [ -n "$REAL_BASE" ]; then
        case "$REAL_PATH" in
          "$REAL_BASE"/*)
            exit 0
            ;;
        esac
      fi
    fi

    cat >&2 <<'EOF'
[gwm enforcer] 外部 path への EnterWorktree は許可していません。

  新規 worktree:
    EnterWorktree(name: <branch-name>)  # WorktreeCreate hook 経由で gwm を実行
  既存 GWM worktree:
    EnterWorktree(path: <gwm の出力パス>)

worktree_base_path は ~/.config/gwm/config.toml で管理されています。
EOF
    exit 2
    ;;
  Bash)
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // .command // ""')

    # 判定は共通の境界正規化（perl）と python3 の tokenizer に委ねている。どちらかが
    # 無いと pipeline が 127 で終わり「worktree add ではない」と誤読して素通りする
    # （冒頭の fail-closed 契約に反する）。無関係な Bash を巻き込まないよう、
    # worktree に言及するコマンドだけ安全側に倒す。
    mentions_worktree=0
    if printf '%s' "$COMMAND" | command grep -qE '(^|[^A-Za-z0-9_-])worktree([^A-Za-z0-9_-]|$)'; then
      mentions_worktree=1
    fi
    if [ "$mentions_worktree" -eq 1 ] && ! command -v python3 >/dev/null 2>&1; then
      echo "[gwm enforcer] worktree 判定に必要な python3 が見つかりません（安全側に倒してブロックします）" >&2
      exit 2
    fi
    if [ "$mentions_worktree" -eq 1 ] && ! normalize_command_available; then
      echo "[gwm enforcer] worktree 判定に必要な perl が見つかりません（安全側に倒してブロックします）" >&2
      exit 2
    fi
    if [ "$mentions_worktree" -eq 0 ]; then
      exit 0
    fi

    # 標準形（quote 中和・subshell / $( ) の畳み込み・git グローバルオプション除去済み）
    # を tokenizer に渡す。改行は起点なので `;` に寄せてから字句解析する。
    if ! NORMALIZED=$(normalize_command "$COMMAND"); then
      echo "[gwm enforcer] worktree 判定の前処理に失敗しました（安全側に倒してブロックします）" >&2
      exit 2
    fi
    if printf '%s\n' "$NORMALIZED" | command python3 -c '
import shlex
import sys

try:
    lexer = shlex.shlex(
        sys.stdin.read().replace("\n", " ; "), posix=True, punctuation_chars=";&|()"
    )
    lexer.whitespace_split = True
    tokens = list(lexer)
except ValueError:
    raise SystemExit(1)

separators = {";", "&&", "||", "|", "&"}

for index, token in enumerate(tokens):
    if token != "git":
        continue
    previous = tokens[index - 1] if index else None
    command_start = previous is None or previous in separators or previous == "("
    wrapped_by_rtk = (
        previous == "rtk"
        and (index == 1 or tokens[index - 2] in separators | {"("})
    )
    if not command_start and not wrapped_by_rtk:
        continue

    if tokens[index + 1 : index + 3] == ["worktree", "add"]:
        raise SystemExit(0)

raise SystemExit(1)
'; then
      cat >&2 <<'EOF'
[gwm enforcer] git worktree add ではなく gwm を使ってください。

  gwm add <branch>                 # 新規 worktree（main から）
  gwm add --from <base> <branch>   # base ref 指定
  gwm add -r <remote-branch>       # remote branch から
  gwm list                         # 既存一覧

worktree の配置先は ~/.config/gwm/config.toml の worktree_base_path で統一されます。
EOF
      exit 2
    fi

    if command_origin_matches "$COMMAND" 'claude[[:space:]]+worktree([^A-Za-z0-9_-]|$)'; then
      cat >&2 <<'EOF'
[gwm enforcer] claude worktree ではなく gwm を使ってください。

  gwm add <branch>                 # 新規 worktree
  gwm list                         # 既存一覧
EOF
      exit 2
    fi
    ;;
esac

exit 0

#!/bin/bash
# RTK auto-rewrite hook for PreToolUse:Bash (Claude Code / Codex / pi / omp / opencode)
#
# 書き換え判定そのものは rtk 0.48+ の `rtk hook claude` に委譲する（upstream が
# 単一の SSOT として持つエンジン。`rtk rewrite <cmd>` で同じ判定を単体確認できる）。
# 2026-09-14 まではこの hook が独自の正規表現ラダーで判定していたが、upstream が
# `rg` を `rtk rg`（rg セマンティクス維持）に振るようになった一方、こちらは
# `rtk grep`（system grep へフォールバックし再帰も rg 独自フラグも失う）に振り続け、
# ディレクトリ検索が無言で 0 件になる事故が起きた。判定を二重管理しない。
#
# ここに残すのは upstream が面倒を見ない、この環境固有のガードだけ。

# Guards: skip silently if dependencies missing
if ! command -v rtk &>/dev/null || ! command -v jq &>/dev/null; then
  exit 0
fi

set -euo pipefail

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$CMD" ]; then
  exit 0
fi

# heredoc: `rtk hook claude` は制御文字を含む JSON のパースに失敗してエラーを
# stdout に出す。書き換える価値も無いので手前で降りる。
case "$CMD" in
  *'<<'*) exit 0 ;;
esac

# 複数行コマンド: upstream は 1 行目だけを書き換えてスクリプトの途中に rtk を
# 混ぜ込む。スクリプト全体の意味を読まずに触らない方針なので降りる。
case "$CMD" in
  *$'\n'*) exit 0 ;;
esac

# package.json の script 経由の実行: upstream は script 名だけを見て既知ツールに
# 振る（0.48.0 実測: `pnpm run lint` も省略形の `pnpm lint` も `rtk lint`、
# `npm run vitest` → `rtk vitest`、`pnpm tsc` → `rtk tsc`）。script の中身が
# `nx run-many -t lint` や `tsc --noEmit` だと、検証したいものと別のツールが走って
# 「通った」ことになる。何が動くかは package.json 次第で hook からは読めない。
# そこでパッケージマネージャ自身の subcommand だけ委譲し、それ以外（script の
# 可能性がある形）には触らない。未知の subcommand は script 側に倒す（fail-safe）。
case "$CMD" in
  npm\ *|pnpm\ *|yarn\ *|bun\ *)
    PM_SUBCMD="${CMD#* }"
    PM_SUBCMD="${PM_SUBCMD%% *}"
    case "$PM_SUBCMD" in
      install|i|add|remove|rm|uninstall|update|up|list|ls|outdated|why|exec|dlx|link|unlink|audit|pack|publish) ;;
      *) exit 0 ;;
    esac
    ;;
esac

REWRITTEN_JSON=$(printf '%s' "$INPUT" | rtk hook claude 2>/dev/null) || exit 0

# 書き換え不要（upstream は無出力で exit 0）
if [ -z "$REWRITTEN_JSON" ]; then
  exit 0
fi

REWRITTEN_CMD=$(
  echo "$REWRITTEN_JSON" | jq -r '.hookSpecificOutput.updatedInput.command // empty' 2>/dev/null
) || exit 0

if [ -z "$REWRITTEN_CMD" ]; then
  exit 0
fi

# Claude Code の worktree 隔離ガードは `rtk git ...` を「git を operand に持つ未知の
# launcher」と見て、どのディレクトリで動くか読めないという理由で拒否する（2026-09-10 実測。
# git を rtk の直後に置いても通らないため、rtk 経由では原理的に通せない）。worktree
# セッションでは書き換えを諦めて素の git を通す。main checkout では従来どおり節約する。
in_git_worktree() {
  case "$(git rev-parse --git-dir 2>/dev/null)" in
    */.git/worktrees/*) return 0 ;;
    *) return 1 ;;
  esac
}

case "$REWRITTEN_CMD" in
  *'rtk git '*)
    if in_git_worktree; then
      exit 0
    fi
    ;;
esac

printf '%s\n' "$REWRITTEN_JSON"

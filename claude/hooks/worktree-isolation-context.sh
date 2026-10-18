#!/bin/bash
# PostToolUse:EnterWorktree — worktree に入った時だけ、隔離検査に通る Bash の書き方を
# 文脈へ差し込む。常駐の CLAUDE.md に置くと全セッションが払うコストを、隔離中の
# セッションだけに寄せる。2026-09-18〜10-18 の 30 日で隔離検査の拒否が 510 件あり、
# git 以外（rg / pnpm / for）の連結や共有 checkout のパス指定も拒否されていた。
set -uo pipefail

cat >/dev/null

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "worktree 隔離中の Bash: 1 呼び出し 1 コマンドにし、`;`・`&&`・`||`・先頭の変数代入（`W=...;`）・`$VAR` や `$(…)` を含む引数を使わない（git 以外のコマンドも隔離検査が拒否する）。git は `-C` を付けずこの worktree の cwd で実行する。パスは共有 checkout ではなく worktree の絶対パスを渡す。"
  }
}'

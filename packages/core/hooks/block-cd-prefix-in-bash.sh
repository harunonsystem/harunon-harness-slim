#!/bin/bash
# Bash コマンド先頭の `cd <絶対パス> && ...` をブロックする。
#
# なぜ: Claude Code 本体が「cd in a compound command can trigger a permission
# prompt」と警告しているとおり、先頭 cd を含む複合コマンドは auto mode の
# classifier に拒否される。cclens の実測（2026-08-28、1144 セッション）では
# blocked-by-hook 535 件のうち 263 件が classifier 拒否で、その target 上位は
# すべて `cd ~/projects/worktrees/...` 形式だった。cd は Bash 呼び出しの 21%
# （7054 回）を占めており、単一の是正点としては最大。
#
# 何を止めるか: 先頭が `cd` で、移動先がリテラルの絶対パス（/ または ~ 始まり）
# かつ後続コマンドが続く形だけ。command substitution（`cd "$(git rev-parse
# --show-toplevel)" && ...`）と相対パス、単独の `cd` は通す。前者は skill 本文で
# 使われている定型で、パスを外から与えていないため誤爆させない。
set -euo pipefail

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

COMMAND=$(echo "$INPUT" | jq -r '.command // .tool_input.command // ""')

# command-normalize.sh は意図的に source しない。正規化は quote と command
# substitution を潰して `cd "$(git rev-parse --show-toplevel)" && x` を
# `cd ~ && x` に書き換えるため、この hook が判定したい「リテラルの絶対パスが
# 先頭に打たれたか」という区別そのものが消える（危険コマンド検出では中身を
# 覗くのが正しく、style guard では逆に有害）。生のコマンドで判定する。

# 判定は bash の [[ =~ ]] で行い、grep へのパイプは使わない。理由は 2 つ:
#   1. grep は ^ を行頭として評価するため、`echo x` の次の行に cd が来ただけで
#      「先頭の cd」と誤判定する。ここで見たいのは入力全体の先頭コマンド
#   2. set -o pipefail 下では、先頭行で一致して grep -q が早期終了したときに
#      echo が SIGPIPE(141) で死に、パイプライン全体が偽になる。大きな heredoc を
#      含むコマンドが「一致したのに allow」で素通りする
#
# 先頭 cd + リテラル絶対パス + 後続コマンド。パスは quote 済み・バックスラッシュ
# エスケープ済み・非 quote のいずれも受ける。エスケープを取り逃がすと
# 「クォートすれば通る」抜け道になるため。後続は && / ; / 改行のいずれか。
NL=$'\n'
CD_PREFIX_ERE="^[[:space:]]*cd[[:space:]]+(\"[~/][^\"]*\"|'[~/][^']*'|[~/]([^[:space:]]|\\\\.)*)[[:space:]]*(&&|;|${NL}[[:space:]]*[^[:space:]])"
if [[ "$COMMAND" =~ $CD_PREFIX_ERE ]]; then
  cat >&2 <<'MSG'
コマンド先頭の `cd <絶対パス> &&` は auto mode の classifier に拒否されます。作業ディレクトリを移さずに実行してください:

  git   → git -C <dir> <subcommand>
  pnpm  → pnpm -C <dir> / npm --prefix <dir>
  script→ <dir>/scripts/foo.sh のように絶対パスで直接起動
  その他 → 引数を絶対パスで渡す

どうしても cwd が要るコマンドは subshell に入れて先頭以外に置いてください: ( cd <dir> && <cmd> )
MSG
  exit 2
fi

exit 0

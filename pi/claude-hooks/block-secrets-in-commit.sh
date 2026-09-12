#!/bin/bash
# PreToolUse:Bash — staged 差分にシークレットが含まれる commit をブロックする
#
# verify-before-commit.sh から分離した。あちらは Claude Code の additionalContext に
# チェックリストを注入する hook で、hook 移植ポリシー (b)（Claude の仕様補正が目的の
# hook は移植しない）に当たるため Claude / codex にしか配れない。シークレット検出は
# runtime を問わない普遍ポリシー (a) なので、独立した hook にして全 runtime に配る。
set -euo pipefail

INPUT=$(cat)

# Fast path: skip if command doesn't contain "commit"
case "$INPUT" in
  *commit*) ;;
  *) exit 0 ;;
esac

# 壊れた JSON でも fail-open（jq のパース失敗で hook がクラッシュしないよう空にフォールバック）
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# lib 不在は配布漏れ。この hook は deny する経路を持つ required hook なので、
# 判定層の消失を allow に倒さず deny にする。
NORMALIZE_LIB="$HOOK_DIR/lib/command-normalize.sh"
if [ ! -r "$NORMALIZE_LIB" ]; then
  echo "commit 前のシークレット検査に必要な lib が読めません: ${NORMALIZE_LIB}（安全側に倒してブロックします）" >&2
  exit 2
fi
# shellcheck source=lib/command-normalize.sh
source "$NORMALIZE_LIB"

# commit 検出は共通の境界正規化に乗せる（改行 / & / subshell / $( ) を起点として扱い、
# git のグローバルオプション `-C <path>` は正規化側が剥がす）。
if ! normalize_command_available; then
  echo "commit 前のシークレット検査に必要な perl が見つかりません（安全側に倒してブロックします）" >&2
  exit 2
fi
origin_rc=0
command_origin_matches "$CMD" '(git|rtk git)[[:space:]]+commit([^A-Za-z0-9_-]|$)' || origin_rc=$?
case $origin_rc in
  0) ;;
  1) exit 0 ;;
  *)
    echo "commit 前のシークレット検査のコマンド前処理に失敗しました（安全側に倒してブロックします）" >&2
    exit 2
    ;;
esac

# --- 「hook が見る index」と「実際に commit される内容」が食い違う形を先に弾く。
# PreToolUse は Bash の実行“前”に走るので、同じ呼び出しの中で stage される変更は
# まだ index に無い。`git add secret.txt && git commit` や `git commit -a` を素通しすると、
# 検査が空振りしたまま実際にはシークレットごと commit される。
if printf '%s' "$CMD" | perl -ne 'exit(/(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+(?:-[^\s]+\s+)*add\b/ ? 0 : 1)'; then
  echo "同じコマンドの中で git add と commit を行っています。" >&2
  echo "  PreToolUse の時点では add がまだ実行されておらず、staged 差分のシークレット検査が空振りします。" >&2
  echo "  add と commit を別々のコマンドとして実行してください。" >&2
  exit 2
fi
if printf '%s' "$CMD" | perl -ne '
  exit(/(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+(?:-[^\s]+\s+|-C\s+\S+\s+)*commit\b[^&;|]*\s-(?:[A-Za-z]*a[A-Za-z]*)\b/ ? 0 : 1)
'; then
  echo "git commit -a は working tree の変更を commit 時に stage するため、" >&2
  echo "  PreToolUse 時点の index を見るシークレット検査が対象を取りこぼします。" >&2
  echo "  git add で明示的に stage してから commit してください。" >&2
  exit 2
fi

# --- commit の対象 repo を解決する。hook プロセスの cwd で git diff --cached を実行すると、
# `cd /repo-b && git commit ...` や `git -C /repo-b commit ...` の形で別リポジトリを
# commit しているときに hook 自身の cwd（= 呼び出し元 repo）を見てしまい、判定が的外れになる。
# 優先順位: (a) commit を打つ git 呼び出し自身の -C <path> → (b) commit 呼び出し
# より前にある最後の `cd <path> &&` → (c) どちらも無ければ cwd。
TARGET=$(printf '%s' "$CMD" | perl -ne '
  if (/(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+-C\s+(\S+)\s+commit\b/) {
    print $1;
    exit;
  }
  if (/^(.*?)(?:^|&&|;|\|)\s*(?:git|rtk\s+git)\s+commit\b/s) {
    my $prefix = $1;
    if ($prefix =~ /cd\s+(\S+)\s*$/) {
      print $1;
    }
  }
')
TARGET="${TARGET%\"}"; TARGET="${TARGET#\"}"
TARGET="${TARGET%\'}"; TARGET="${TARGET#\'}"
TARGET="${TARGET:-$(pwd)}"

# 対象 repo を解決できないまま素通しにしない。`git -C $PWD commit` のように hook 側では
# 未展開のまま渡る形（シェルは後で展開して commit を実行する）や、quote / 追加の global
# option で resolver を外せる形があり、allow に倒すと検査ごと回避できてしまう。
if ! git -C "$TARGET" rev-parse --show-toplevel &>/dev/null; then
  echo "commit 対象の repo を解決できませんでした: ${TARGET}（検査できないため安全側に倒してブロックします）" >&2
  echo "  対象を明示して単独の commit コマンドで実行してください（変数展開を含む -C は解決できません）" >&2
  exit 2
fi

# --- staged 差分のシークレット検出（block）。高精度パターンのみ、エントロピー
# ヒューリスティックは使わない。ファイル・行を提示してユーザーの判断を仰ぐ。
# パターン文字列自体（このスクリプトや danger-rules.json の diff）には自己マッチ
# しない: 各パターンの直後に来る文字クラスがブラケット/波括弧の regex 構文
# そのものとは一致しない構造になっている（scripts/tests/test_misc_hooks.py で担保）。
# pipefail 下で staged diff の取得や perl の失敗を検出できるようにする。`|| echo ""` で
# 空に潰すと、textconv / external diff helper の失敗が「検出なし」と同じになり、
# required な security hook が黙って allow に倒れる。
# diff の取得と走査を別々に実行して、それぞれの終了コードを見る（コマンド置換の中で
# パイプを組むと PIPESTATUS が取れない）。
set +e
STAGED_DIFF=$(git -C "$TARGET" diff --cached -U0)
diff_rc=$?
set -e
if [ "$diff_rc" -ne 0 ]; then
  echo "staged 差分を取得できませんでした（git diff --cached: ${diff_rc}）。" >&2
  echo "  検査できていないため安全側に倒してブロックします。" >&2
  exit 2
fi

set +e
SECRET_HITS=$(printf '%s\n' "$STAGED_DIFF" | perl -ne '
  if (/^\+\+\+ b\/(.+)$/) { $file = $1; $line = 0; next; }
  if (/^@@ -\d+(?:,\d+)? \+(\d+)/) { $line = $1; next; }
  next unless /^\+/;
  next if /^\+\+\+ /;
  my $content = substr($_, 1);
  chomp $content;
  if ($content =~ /AKIA[0-9A-Z]{16}/) {
    print "$file\t$line\tAWS Access Key ID\n";
  } elsif ($content =~ /-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY/) {
    print "$file\t$line\tPrivate Key\n";
  } elsif ($content =~ /ghp_[A-Za-z0-9]{36}/) {
    print "$file\t$line\tGitHub Personal Access Token\n";
  } elsif ($content =~ /sk-ant-[A-Za-z0-9-]{20,}/) {
    print "$file\t$line\tAnthropic API Key\n";
  }
  $line++;
')
scan_rc=$?
set -e
if [ "$scan_rc" -ne 0 ]; then
  echo "staged 差分のシークレット走査に失敗しました（scanner: ${scan_rc}）。" >&2
  echo "  検査できていないため安全側に倒してブロックします。" >&2
  exit 2
fi

if [ -n "$SECRET_HITS" ]; then
  {
    echo "staged 差分にシークレットらしき文字列を検出しました。誤検知に見えてもユーザーの判断を仰いでください:"
    echo "$SECRET_HITS" | while IFS=$'\t' read -r hit_file hit_line hit_kind; do
      echo "  - ${hit_file}:${hit_line} (${hit_kind})"
    done
  } >&2
  exit 2
fi

exit 0

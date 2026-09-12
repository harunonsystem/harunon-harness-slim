#!/bin/bash
# 共有ライブラリ: Codex レビューゲート用 KEY / フラグパス算出
#
# 提供する関数:
#   codex_review_key        — git root + branch から KEY（shasum 第 1 フィールド）を echo する
#   codex_review_gate_flag  — $CODEX_REVIEW_FLAG_DIR/.codex-review-gate-<key> を echo する
#   codex_review_done_flag  — $CODEX_REVIEW_FLAG_DIR/.codex-review-done-<key> を echo する
#
# KEY は repo + branch 単位（レビューサイクル単位）。同一 repo の別ブランチで
# 過去に実施したレビューが、新しいブランチの初回レビューをブロックしないようにする。
# 再現: printf '%s\n%s\n' "$(git rev-parse --show-toplevel)" "$(git rev-parse --abbrev-ref HEAD)" | shasum
#
# 注意: repo 外の場合の「早期 exit」判定は各 hook 側に残す。
#       このライブラリは判定を行わず、repo 外では "none" を使った KEY を返す。
#
# CODEX_REVIEW_FLAG_DIR: フラグ格納先ディレクトリ（未設定時は ~/.claude/review-gate）。
# テストがフラグ名前空間を隔離するための注入点。
#
# 旧デフォルトは /tmp 直下だったが、そこは Claude の Bash sandbox の write allowlist 外
# （許可は /tmp/claude まで）。approve-push.sh の実行に sandbox 解除が要り、auto mode の
# classifier に拒否されて「ユーザー承認を記録するスクリプト」自体が打てなくなった
# （2026-08-29）。~/.claude/ は allowlist 内なので sandbox のまま書ける。
# フラグを書く hook はすべてこの lib を source するため、ディレクトリ作成はここで 1 回行う。
: "${CODEX_REVIEW_FLAG_DIR:=$HOME/.claude/review-gate}"
mkdir -p "$CODEX_REVIEW_FLAG_DIR" 2>/dev/null || true

# CMD → 対象 repo 解決 CLI（policy/repo_target.py）への絶対パス。source 時点
# （このファイル自身の場所）から 1 回だけ計算する。
_REVIEW_GATE_LIB_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
_REPO_TARGET_CLI="$_REVIEW_GATE_LIB_DIR/../../policy/repo_target.py"

# git repo のルートパスを取得する。repo 外では空文字を返す。
_codex_review_git_root() {
  git rev-parse --show-toplevel 2>/dev/null || echo ""
}

# 現在のブランチ名を取得する。detached HEAD では "HEAD"、repo 外では空文字を返す。
_codex_review_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
}

# KEY を算出して echo する。
# repo 外 (git root / branch が空) の場合は "none" を入力として shasum にかける。
codex_review_key() {
  local git_root branch
  git_root=$(_codex_review_git_root)
  branch=$(_codex_review_branch)
  printf '%s\n%s\n' "${git_root:-none}" "${branch:-none}" | shasum | cut -d' ' -f1
}

# gate フラグファイルのパスを echo する。
codex_review_gate_flag() {
  echo "${CODEX_REVIEW_FLAG_DIR}/.codex-review-gate-$(codex_review_key)"
}

# done フラグファイルのパスを echo する。
codex_review_done_flag() {
  echo "${CODEX_REVIEW_FLAG_DIR}/.codex-review-done-$(codex_review_key)"
}

# difit done フラグファイルのパスを echo する（KEY は codex_review_key を流用）。
difit_done_flag() {
  echo "${CODEX_REVIEW_FLAG_DIR}/.difit-done-$(codex_review_key)"
}

# push 承認フラグファイルのパスを echo する（KEY は codex_review_key を流用）。
push_approved_flag() {
  echo "${CODEX_REVIEW_FLAG_DIR}/.push-approved-$(codex_review_key)"
}

# gh pr merge / close 承認フラグファイルのパスを echo する（KEY は codex_review_key を流用。
# 中身は承認した PR 番号）。
pr_approved_flag() {
  echo "${CODEX_REVIEW_FLAG_DIR}/.pr-approved-$(codex_review_key)"
}

# gate フラグに現在の HEAD を書き込み、bypass ログに記録する。
# codex-review-bypass.sh（手動 bypass）と block-pr-without-codex-review.sh
# （review-router.sh による自動 bypass）の両方から共有する。
codex_review_record_bypass() {
  local reason="$1"
  local log="${2:-$HOME/.claude/codex-review-bypass.log}"
  local flag head branch git_root
  flag=$(codex_review_gate_flag)
  head=$(git rev-parse HEAD 2>/dev/null)
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  git_root=$(git rev-parse --show-toplevel 2>/dev/null)
  mkdir -p "$(dirname "$log")"
  echo "$head" > "$flag"
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] BYPASS repo=$git_root branch=$branch head=${head:0:7} reason=\"$reason\"" >> "$log"
}

# デフォルトブランチ名を解決する（origin/HEAD → main → master の順）。
# 解決できなければ空文字を返す（呼び出し元は router 呼び出しをスキップする）。
_codex_review_default_branch() {
  local ref
  ref=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's#^refs/remotes/origin/##')
  if [ -n "$ref" ]; then
    echo "$ref"
    return
  fi
  if git rev-parse --verify main > /dev/null 2>&1; then
    echo "main"
    return
  fi
  if git rev-parse --verify master > /dev/null 2>&1; then
    echo "master"
    return
  fi
  echo ""
}

# CMD から `--<flag> <値>` / `--<flag>=<値>` の値を取り出す（無ければ空文字）。
#
# flag 名は ARGV ではなく環境変数で渡す。`perl -e '...' --base` は `--base` を
# perl 自身のスイッチとして解釈して "Unrecognized switch" で落ちる。
_codex_review_flag_value() {
  local cmd="$1"
  local flag="$2"
  printf '%s' "$cmd" | CODEX_REVIEW_FLAG_NAME="$flag" perl -e '
local $/;
my $s = <STDIN>;
my $f = $ENV{CODEX_REVIEW_FLAG_NAME};
if ($s =~ /(?:^|\s)\Q$f\E(?:=|\s+)("[^"]*"|'\''[^'\'']*'\''|\S+)/) {
  my $v = $1;
  $v =~ s/^["'\'']//;
  $v =~ s/["'\'']$//;
  print $v;
}
'
}

# companion（plugins/.../scripts/lib/git.mjs の detectDefaultBranch）と同じ順序で
# デフォルトブランチを解決する。解決できなければ 1 を返す。
#
# router 用の `_codex_review_default_branch` とは別物。あちらは diff 分類のための
# 解決で、`git rev-parse --verify` がローカルと remote-tracking のどちらにも当たる。
# こちらは「companion が実際にどの ref を base に選ぶか」を再現する必要があるため、
# ローカルブランチを先に見る companion の順序を厳密に写す。両者を統合すると
# router の分類挙動が変わるので、意図的に分けている。
_codex_review_companion_default_branch() {
  local ref candidate
  ref=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null || echo "")
  case "$ref" in
    refs/remotes/origin/*)
      echo "${ref#refs/remotes/origin/}"
      return 0
      ;;
  esac
  for candidate in main master trunk; do
    if git show-ref --verify --quiet "refs/heads/$candidate"; then
      echo "$candidate"
      return 0
    fi
    if git show-ref --verify --quiet "refs/remotes/origin/$candidate"; then
      echo "origin/$candidate"
      return 0
    fi
  done
  return 1
}

# レビュー対象が空か判定する（0 = 空、1 = 対象あり / 判定不能）。
#
# 空対象で review を回すと Codex は何も見ずに返り、レビュー済みフラグだけが立つ。
# その状態で PR gate は「レビュー済み」として通ってしまう。
#
# 判定は **companion の resolveReviewTarget と同じ引数・同じ base** で行う。gate が
# 独自に base を決めると、レビュアーが見るものと gate が見るものがずれて保護が
# 素通りする（`--base HEAD` や `--scope working-tree` を渡した空レビューが通る、
# origin/HEAD 不在時に companion はローカル main を選ぶのに gate は origin/main を
# 見る、など。2026-09-05 の Codex review P1）。
#
# companion の解決順（lib/git.mjs resolveReviewTarget）:
#   1. --base <ref> があれば無条件に branch mode（dirty でも working-tree にしない）
#   2. --scope working-tree なら working-tree mode
#   3. --scope branch なら detectDefaultBranch を base に branch mode
#   4. auto かつ dirty なら working-tree mode
#   5. auto かつクリーンなら detectDefaultBranch を base に branch mode
#
# 判定不能な場合（base 解決失敗・不正な scope・merge-base なし）は 1 を返す
# fail-open。レビュー自体を止めるのは gate の責務ではなく、companion 側が
# 自分でエラーにする。
# 空判定が 0 を返したとき、呼び出し元が deny 理由に使う解決結果ラベル
# （companion がどの対象を見るつもりだったかを人間に見せるため）。
CODEX_REVIEW_EMPTY_TARGET_LABEL=""

codex_review_target_is_empty() {
  local cmd="$1"
  local base scope mode

  CODEX_REVIEW_EMPTY_TARGET_LABEL=""

  git rev-parse --show-toplevel > /dev/null 2>&1 || return 1

  base=$(_codex_review_flag_value "$cmd" "--base")
  scope=$(_codex_review_flag_value "$cmd" "--scope")
  : "${scope:=auto}"

  if [ -n "$base" ]; then
    mode="branch"
  elif [ "$scope" = "working-tree" ]; then
    mode="working-tree"
  elif [ "$scope" = "branch" ]; then
    mode="branch"
    base=$(_codex_review_companion_default_branch) || return 1
  elif [ "$scope" = "auto" ]; then
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
      mode="working-tree"
    else
      mode="branch"
      base=$(_codex_review_companion_default_branch) || return 1
    fi
  else
    # companion が Unsupported review scope で落とす入力。gate は判定しない。
    return 1
  fi

  if [ "$mode" = "working-tree" ]; then
    # companion の getWorkingTreeState().isDirty（staged + unstaged + untracked）と
    # `git status --porcelain` の非空は一致する。
    if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
      # このファイル内では読まないが、呼び出し元（各 hook）が deny メッセージに使う。
      # shellcheck disable=SC2034
      CODEX_REVIEW_EMPTY_TARGET_LABEL="working tree diff（作業ツリーに変更なし）"
      return 0
    fi
    return 1
  fi

  git merge-base "$base" HEAD > /dev/null 2>&1 || return 1
  if git diff --quiet "$base"...HEAD 2>/dev/null; then
    # shellcheck disable=SC2034
    CODEX_REVIEW_EMPTY_TARGET_LABEL="branch diff against ${base}（${base}...HEAD に差分なし）"
    return 0
  fi
  return 1
}

# CMD が Codex レビュー実行コマンドか判定する。
# 対応形式:
#   codex-companion.mjs review ...
#   node "$COMPANION" review ... / node codex-companion.mjs review ...
_codex_review_command_matches() {
  local cmd="$1"
  echo "$cmd" | grep -qE '(codex-companion\.mjs[[:space:]]+review|[[:space:]]node[[:space:]]+("[^"]+"|[^[:space:]]+)[[:space:]]+review)'
}

# CMD 文字列から対象 repo を解決し、そのディレクトリへ cd する。
# 解決ロジックは共有 CLI（policy/repo_target.py）に一本化されている
# （bash / python(kernel) / JS(bridge) の 3 言語がこの 1 実装に到達する）。
#
# 戻り値:
#   0 = 解決済み（CMD に repo 切り替えの指定が無く、呼び出し元 cwd を維持する
#       ケースを含む）
#   1 = 解決不能。呼び出し元は deny / 書き込み中止に倒すこと。理由は
#       REVIEW_GATE_UNRESOLVABLE_REASON にセットする。
#
# python3 / repo_target.py 不在も fail-closed（1 を返す）。無言でフォールバック
# しない — 旧実装（cd 失敗を無視）は repo A の承認で `git -C "<repo-b>" push`
# 等が通る穴だった（2026-07-26 に実測）。
#
# git -C / --cwd を見るのは、承認フラグの KEY（repo root + branch）と HEAD 照合を
# **push/PR 対象の repo** で解決するため。
review_gate_resolve_target_repo() {
  local cmd="$1"
  local base result status error_file

  REVIEW_GATE_UNRESOLVABLE_REASON=""

  if ! command -v python3 >/dev/null 2>&1; then
    REVIEW_GATE_UNRESOLVABLE_REASON="repo 解決に必要な python3 が見つかりません"
    return 1
  fi
  if [ ! -r "$_REPO_TARGET_CLI" ]; then
    REVIEW_GATE_UNRESOLVABLE_REASON="repo 解決に必要な repo_target.py が読めません: ${_REPO_TARGET_CLI}"
    return 1
  fi

  base="$(pwd)"
  error_file=$(mktemp "${TMPDIR:-/tmp}/harness-repo-target.XXXXXX") || {
    REVIEW_GATE_UNRESOLVABLE_REASON="repo 解決の診断用一時ファイルを作成できません"
    return 1
  }
  # shim の警告は exit 0 でも stderr に出る。成功時の stdout はパスだけとして扱う。
  result=$(printf '%s' "$cmd" | python3 "$_REPO_TARGET_CLI" resolve --base "$base" 2>"$error_file")
  status=$?
  if [ "$status" -ne 0 ]; then
    local error_output
    error_output="$(cat "$error_file")"
    if [ -n "$result" ] && [ -n "$error_output" ]; then
      REVIEW_GATE_UNRESOLVABLE_REASON="$(printf '%s\n%s' "$result" "$error_output")"
    elif [ -n "$result" ]; then
      REVIEW_GATE_UNRESOLVABLE_REASON="$result"
    else
      REVIEW_GATE_UNRESOLVABLE_REASON="$error_output"
    fi
    if [ -z "$REVIEW_GATE_UNRESOLVABLE_REASON" ]; then
      REVIEW_GATE_UNRESOLVABLE_REASON="repo_target.py resolve が失敗しました (exit $status)"
    fi
    rm -f "$error_file"
    return 1
  fi
  rm -f "$error_file"

  if ! cd "$result" 2>/dev/null; then
    # このファイル内では読まないが、呼び出し元（各 hook）が deny メッセージに使う。
    # shellcheck disable=SC2034
    REVIEW_GATE_UNRESOLVABLE_REASON="解決済みディレクトリへ cd できません: $result"
    return 1
  fi
  return 0
}

# CMD 文字列中の `git -C <path>` が指す対象へ cd する（--cwd / cd とは独立した
# 第三の解決経路）。`git -C <repo-b> push …` は cwd が repo A でも repo B に
# 作用するため、cwd 基準のフラグ解決だけでは対象がすり替わる（セキュリティ修正
# C-002）。呼び出し元はこの関数を _codex_review_resolve_cwd の後に呼ぶこと。
#
# 一意に解決できる場合だけ cd して 0 を返す。以下は解決不能として 1 を返し、
# 何もしない（呼び出し元が fail-closed に倒すかどうかは呼び出し元の責務）:
#   - `-C` が 2 回以上出現（どれが有効な指定か静的に確定できない。git は複数の
#     -C を相対パスとして連結するため誤って別解釈すると危険）
#   - 値が `'` / `"` で始まる（quote 内の空白等を安全に外せない）
#   - `-C` の後に値がない
_codex_review_resolve_git_dash_c() {
  local cmd="$1"
  local count target

  count=$(printf '%s' "$cmd" | perl -e '
local $/;
my $s = <STDIN>;
my $n = () = $s =~ /(?:^|[ \t])-C[ \t]+\S/g;
print $n;
')
  if [ "${count:-0}" -ne 1 ]; then
    return 1
  fi

  target=$(printf '%s' "$cmd" | perl -e '
local $/;
my $s = <STDIN>;
print $1 if $s =~ /(?:^|[ \t])-C[ \t]+(\S+)/;
')
  case "$target" in
    \'*|\"*|"") return 1 ;;
  esac

  target="${target/#\~/$HOME}"
  cd "$target" 2>/dev/null || return 1
}

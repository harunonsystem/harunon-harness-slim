#!/bin/bash
# PreToolUse:Bash — コマンド全文を検査し、危険な操作をブロックする
#
# 判定ルールは packages/core/policy/danger-rules.json（SSOT）から実行時に読み込む。
# ルールの追加・変更は table 側で行う（このスクリプトへの直接追記は禁止）。
# table の schema・7表現との整合は scripts/harness_lib/danger_rules.py が検証する。
set -euo pipefail

# unit test 用の source seam: テストが `source` して custom_* / _push_* の
# ヘルパ関数だけを直接呼びたい場合、以下の本体実行（stdin 読み取り・table
# 読み込み・exit）が source 時にも走ってしまうと使い物にならない。
# 直接実行（bash block-dangerous-in-bash.sh）のときだけ本体を走らせる。
_BLOCK_DANGEROUS_SOURCED=0
(return 0 2>/dev/null) && _BLOCK_DANGEROUS_SOURCED=1

if [ "$_BLOCK_DANGEROUS_SOURCED" -eq 0 ]; then
# 判定選別（table の targets）に使う runtime 識別子。未設定・未知値は安全側に
# 倒す（どの rule を実効させるべきか判定できない状態で全 Bash を通すと、
# 危険コマンド判定という安全層が無言で消える）。
case "${HARNESS_RUNTIME:-}" in
  claude|pi|opencode|codex|omp) ;;
  *)
    echo "危険コマンド判定に必要な HARNESS_RUNTIME が未設定または不正です: '${HARNESS_RUNTIME:-}'（安全側に倒してブロックします）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
    exit 2
    ;;
esac

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

# jq が無いと table 読み込みも入力解析も成立しない。table 不在と同じく fail-closed に倒す。
# ここを守らないと exit 127 で終わり、hook protocol では「エラーだが継続」= 安全層の消失になる。
if ! command -v jq >/dev/null 2>&1; then
  echo "危険コマンド判定に必要な jq が見つかりません（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi

# 入力 JSON の解析失敗は deny（exit 2）に倒す。$( ) 内の jq 失敗を set -e に任せると
# exit 1 = hook protocol では「エラーだが継続」になり、壊れた入力を送るだけで
# 危険コマンド判定を素通りできる。
#
# command と dangerouslyDisableSandbox（Bash ツールのパラメータ。custom_codex_companion_sandbox
# が使う）を jq 1 回で取り出す。command は改行を含み得るので行単位の read ではなく
# 末尾の区切り（ASCII Unit Separator \x1f）で切る。
FIELD_SEP=$'\x1f'
if ! INPUT_ROW=$(printf '%s' "$INPUT" | jq -r --arg sep "$FIELD_SEP" '[(.command // .tool_input.command // ""), ((.dangerouslyDisableSandbox // .tool_input.dangerouslyDisableSandbox // false) | tostring)] | join($sep)' 2>/dev/null); then
  echo "危険コマンド判定の入力 JSON を解析できません（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
COMMAND="${INPUT_ROW%"$FIELD_SEP"*}"
DANGEROUSLY_DISABLE_SANDBOX="${INPUT_ROW##*"$FIELD_SEP"}"

# 自身の隣の lib/ を指す。readlink -f で相対・多段 symlink も絶対パスへ解決する
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# 存在確認してから source する（`source 不在ファイル || true` は bash 3.2 の
# set -e 下では || true が効かず即 exit 1 で落ちる既知の癖があるため、
# unreadable のケースでは source 自体を呼ばずに避ける）。
if [ -r "$HOOK_DIR/lib/denial-log.sh" ]; then
  # shellcheck source=lib/denial-log.sh
  source "$HOOK_DIR/lib/denial-log.sh"
fi
TABLE_PATH="$HOOK_DIR/../policy/danger-rules.json"

# lib 不在は配布漏れ（source 失敗で exit 1 になると hook protocol では「エラーだが継続」
# = 安全層の消失）。table 不在と同じく deny に倒し、配線漏れを大声で失敗させる。
NORMALIZE_LIB="$HOOK_DIR/lib/command-normalize.sh"
if [ ! -r "$NORMALIZE_LIB" ]; then
  echo "危険コマンド判定に必要な lib が読めません: ${NORMALIZE_LIB}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
# shellcheck source=lib/command-normalize.sh
source "$NORMALIZE_LIB"

# 判定用の標準形。起点の直後に対象語が来る形へ寄せることで、env prefix・subshell・
# バッククォート・シェルキーワード・git グローバルオプション・interpreter -c の
# ラップを 1 箇所で剥がす（各ルールの正規表現には手を入れない）。詳細は lib 側の冒頭。
if ! normalize_command_available; then
  echo "危険コマンド判定に必要な perl が見つかりません（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
# 前処理の失敗を allow に倒さない。$( ) の失敗は set -e で exit 1 になるが、
# hook protocol では exit 1 は「エラーだが継続」＝ 判定層の消失になる。
if ! NORMALIZED=$(normalize_command "$COMMAND"); then
  echo "危険コマンド判定の前処理に失敗しました（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
if [ -n "$COMMAND" ] && [ -z "$NORMALIZED" ]; then
  echo "危険コマンド判定の前処理が空を返しました（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi

# table が読めない/壊れている場合は fail-closed（安全層の欠落を無言で素通りさせない）。
if [ ! -r "$TABLE_PATH" ]; then
  echo "危険コマンドルール table が読めません: ${TABLE_PATH}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi

# 会社・プロジェクト固有ルール（extras 配布）。無ければ core table のみで動く。
# 存在するのに parse できない場合、そのルール分の安全層が無言で欠落するため
# fail-closed に倒す。origin/wordEnd の定数は core table のものを共用する。
EXTRA_TABLE_PATH="$HOOK_DIR/../policy/danger-rules.extra.json"
RULE_SOURCES=("$TABLE_PATH")
if [ -e "$EXTRA_TABLE_PATH" ]; then
  if ! jq -e '.rules | type == "array"' "$EXTRA_TABLE_PATH" >/dev/null 2>&1; then
    echo "extras 危険コマンドルール table が読めません: ${EXTRA_TABLE_PATH}（安全側に倒してブロックします）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
    exit 2
  fi
  RULE_SOURCES+=("$EXTRA_TABLE_PATH")
fi

# table の読み込みは jq 1 回。各行の先頭フィールドは種別タグ: C = constants + core の
# rules 件数、M = targets の無い rule id、R = 実効 rule（custom/table 両方）。タグを
# 付けるのは、M の中身が空でも行が空にならないようにするため（空行だと `$( )` の
# 末尾改行除去で消え、実効 rule 0 件のとき C 行が M として読まれて全コマンドが
# exit 2 になった。codex review PERF-HOOK-TABLE-001）。フィールド区切りは ASCII Unit
# Separator（\x1f）。jq の @tsv はフィールド内のバックスラッシュを \\ にエスケープ
# してしまい、ERE 正規表現の内容が壊れるため使わない（join() は区切り文字以外の
# エスケープをしない）。
#
# 実効 rule は targets に $HARNESS_RUNTIME を含むものだけを含み、table 行はさらに
# match.ere を持つものだけを含む。実効 action が confirm の rule は選別段階で除外
# する（hook は対話確認できず、ask は各 runtime の native 層が所有するため）。
if ! TABLE_ROWS=$(jq -s -r --arg sep "$FIELD_SEP" --arg runtime "$HARNESS_RUNTIME" '
  (["C", .[0].constants.originEre, .[0].constants.chainOnlyOriginEre, .[0].constants.wordEndEre, (.[0].rules | length | tostring)] | join($sep)),
  (["M", ([.[] | .rules[] | select(has("targets") | not) | .id] | join(", "))] | join($sep)),
  (.[] | .rules[]
    | select(.targets | index($runtime))
    | select(
        (.impl // "table") == "custom"
        or (
          (.impl // "table") == "table"
          and (.match.ere != null)
        )
      )
    | select(((.overrides[$runtime].action) // .action) != "confirm")
    | [
        "R",
        .id,
        (.impl // "table"),
        (.match.ere // ""),
        (.match.origin // "default"),
        ((.match.wordEnd // false) | tostring),
        ((.overrides[$runtime].action) // .action),
        (.message // "")
      ]
    | join($sep))
' "${RULE_SOURCES[@]}" 2>/dev/null); then
  echo "危険コマンドルール table の読み込みに失敗しました: ${TABLE_PATH}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
# C 行と M 行を剥がす（タグ付きなので M が空でも行は残る）。R 行が無いときは空にする
# （`${var#*\n}` は改行が無いと何も剥がさず M 行がそのまま残る）。
CONSTANTS_ROW="${TABLE_ROWS%%$'\n'*}"
TABLE_ROWS="${TABLE_ROWS#*$'\n'}"
MISSING_ROW="${TABLE_ROWS%%$'\n'*}"
if [[ "$TABLE_ROWS" == *$'\n'* ]]; then
  TABLE_ROWS="${TABLE_ROWS#*$'\n'}"
else
  TABLE_ROWS=""
fi
IFS="$FIELD_SEP" read -r row_tag ORIGIN CHAIN_ONLY_ORIGIN WORD_END RULE_COUNT <<< "$CONSTANTS_ROW"
if [ "$row_tag" != "C" ]; then
  echo "危険コマンドルール table の読み込み結果が想定外です: ${TABLE_PATH}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
IFS="$FIELD_SEP" read -r row_tag MISSING_TARGETS_IDS <<< "$MISSING_ROW"
if [ "$row_tag" != "M" ]; then
  echo "危険コマンドルール table の読み込み結果が想定外です: ${TABLE_PATH}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
# rules が欠落/空の table は constants の読み込みが成功してもループが空回りして
# fail-open になるため、ここで明示的に fail-closed にする。
if [ -z "$RULE_COUNT" ] || [ "$RULE_COUNT" -eq 0 ]; then
  echo "危険コマンドルール table に rules がありません: ${TABLE_PATH}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi

# targets は rule ごとの選別（HARNESS_RUNTIME による対象判定）の前提であり、
# 欠落したまま jq の index() 選別に渡すと「対象外」と「壊れている」を区別できず
# 無言でスキップ（fail-open）してしまう。custom rule の実装欠落と同じ規律で
# 事前に一括検出して fail-closed にする。
if [ -n "$MISSING_TARGETS_IDS" ]; then
  echo "危険コマンドルール table に targets の無い rule があります: ${MISSING_TARGETS_IDS}（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi

# push 承認フラグのパス解決に使う共有ライブラリ（approve-push.sh と共有）。
# table チェックの後に読むのは、table 不在時の fail-closed メッセージを
# lib 不在で上書きしないため。lib 自体が欠けている場合も fail-closed にする。
if [ ! -r "$HOOK_DIR/lib/review-gate.sh" ]; then
  echo "共有ライブラリが読めません: ${HOOK_DIR}/lib/review-gate.sh（安全側に倒してブロックします）" >&2
  declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "fail-closed" "${COMMAND:-}" || true
  exit 2
fi
# shellcheck source=lib/review-gate.sh
source "$HOOK_DIR/lib/review-gate.sh"
fi # _BLOCK_DANGEROUS_SOURCED（setup）

# --- custom ルールが使う判定ヘルパ ---
# 以下の関数定義は source 時にも常に評価する（テストが直接呼び出すため）。

# push が「単独」か判定する。逐次実行・別行（コマンド置換 / interpreter -c 由来）は
# 単独ではない。読み取り専用シンクへのパイプだけは単独として扱う（2>&1 | tee log）。
_push_is_standalone() {
  printf '%s' "$1" | perl -e '
local $/;
my $s = <STDIN>;
exit 1 if $s =~ /(?:&&|\|\||;|\n)/;
my @seg = split /\|/, $s, -1;
shift @seg;
my $sink = qr/^(?:command[ \t]+)?(?:grep|tee|cat|head|tail|less|more|wc|jq|sort|uniq|cut|tr|column|rtk)(?:[ \t]|$)/;
for my $seg (@seg) {
    $seg =~ s/^[ \t]+//;
    exit 1 unless $seg =~ $sink;
}
exit 0
'
}

# push が保護 ref（main / master）を書き換えるか、強制上書きかを判定する。
# 引数はトークン単位で見る。--force-with-lease は feature 相手なら許容（rules/git-safety.md）。
_push_targets_protected_ref() {
  printf '%s' "$1" | perl -e '
local $/;
my $s = <STDIN>;
$s =~ /(?:\bgit|\brtk[ \t]+git)[ \t]+push[ \t]*(.*)/ or exit 1;
my %takes_value = map { $_ => 1 } qw(-o --push-option --repo --receive-pack --exec);
my $skip = 0;
for my $t (split /\s+/, $1) {
    next unless length $t;
    if ($skip) { $skip = 0; next; }
    if ($t =~ /^-/) {
        my ($name) = $t =~ /^([^=]+)/;
        $skip = 1 if $takes_value{$name} && $t !~ /=/;
        exit 0 if $t eq "--force" || $t eq "--force-if-includes";
        exit 0 if $t =~ /^-[A-Za-z]*f[A-Za-z]*$/;
        next;
    }
    exit 0 if $t =~ /^\+/;
    my $dst = ($t =~ /:([^:]*)$/) ? $1 : $t;
    $dst =~ s{^\+}{};
    $dst =~ s{^refs/heads/}{};
    exit 0 if $dst eq "main" || $dst eq "master";
}
exit 1
'
}

# --- impl: "custom" ルール（table では表現しきれない手書きロジックを関数として温存）---

# rule: git-commit-and-push-same-command
custom_git_commit_and_push_same_command() {
  # git commit + git push を1コマンドに詰め込むパターン（分離を強制）
  if ere_matches "$NORMALIZED" "${ORIGIN}(git|rtk git)[[:space:]]+commit" && \
     ere_matches "$NORMALIZED" "${ORIGIN}(git|rtk git)[[:space:]]+push"; then
    echo "git commit と git push を1コマンドにまとめないでください。commit → 確認 → push の順で分離してください" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-commit-and-push-same-command" "${COMMAND:-}" || true
    exit 2
  fi
}

# rule: git-push
custom_git_push() {
  # approve-push で発行した承認フラグが現在の HEAD と一致するときだけ push を許す。
  # 承認済みでも exit 0 せず return するのは、後続ルールの評価を続けるため。
  # 検出パターンと deny メッセージは table（danger-rules.json）が SSOT。
  # ループが渡す $ere / $message を使い、ここに literal を持たない。
  # git-push の match.origin は "default" 宣言なので prefix は $ORIGIN。
  #
  # --git-dir / --work-tree（= 形式・空白区切り形式の両方）は -C と同じく
  # cwd と無関係な対象 repo を指定できる。しかも command-normalize.sh の strip
  # 正規表現は -C/-c と異なり "=" 形にしか対応していないため、空白区切り形式
  # （`git --git-dir /repo-b/.git push …`）は $NORMALIZED 上で git と push が
  # 隣接せず、次の $NORMALIZED マッチが不一致になってこの関数ごと return して
  # しまう（＝承認なしで push が通ってしまう）。そのため raw $COMMAND を直接見て
  # 通常マッチより先に検出し、解決を試みず一律 deny する（対話利用で正当に
  # 使う形ではないため fail-closed が安い）。
  if ere_matches "$COMMAND" "${ORIGIN}(git|rtk git)[[:space:]]" \
     && ere_matches "$COMMAND" '(^|[[:space:]])--(git-dir|work-tree)(=|[[:space:]])' \
     && ere_matches "$COMMAND" '(^|[[:space:]])push([[:space:]]|$)'; then
    echo "${message}。--git-dir / --work-tree を指定した push は承認の対象 repo を確定できません" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  ere_matches "$NORMALIZED" "${ORIGIN}${ere}" || return 0

  local flag current_head push_count flag_mtime flag_age ttl

  # 承認が効くのは「単独・1 回の push」だけ。チェイン / subshell / 複数 push を
  # 許すと次の 2 つが成立してしまう:
  #   (a) `git switch other && git push` で、hook 時点では承認済み HEAD を検証しつつ
  #       実行時に別ブランチの未承認 HEAD を push できる
  #   (b) 1 コマンドの複数 push で、承認した HEAD 以外の ref も同時に送れる
  push_count=$(echo "$NORMALIZED" | command grep -coE "$ere" || true)
  if ! _push_is_standalone "$NORMALIZED" || [ "${push_count:-0}" -ne 1 ]; then
    echo "${message}。承認が適用されるのは単独の push コマンドのみです（チェイン・subshell・複数 push は対象外）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  # 保護 ref への push は承認があっても通さない。table の git-push-protected は
  # match.ere を持たず opencode/omp の glob 専用なので、claude 側はここで判定する。
  # --force-with-lease は feature branch 相手なら許容される（rules/git-safety.md）。
  # トークン単位で見るのは、正規表現の語境界判定では
  # feature:main / HEAD:refs/heads/main / :main / -fu のような FN を塞げないため。
  if _push_targets_protected_ref "$NORMALIZED"; then
    echo "${message}。保護 ref への push（main / master 指定・force・+refspec）は承認では通せません" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  # 承認の主体（repo root + branch + HEAD）を対象 repo で確定する。解決不能
  # （--git-dir/--work-tree、複数 cd/-C、存在しないパス等）は推測せず deny する。
  # 解決を怠ると別 repo の承認フラグを流用できる（C-002）。
  if ! review_gate_resolve_target_repo "$COMMAND"; then
    echo "${message}。承認の対象 repo を確定できません（${REVIEW_GATE_UNRESOLVABLE_REASON}）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi
  # review_gate_resolve_target_repo above already resolves --cwd/cd/git -C with the
  # quote-aware repo_target.py kernel and denies ambiguous or missing targets. Keep
  # the approval check bound to that resolved repository.
  flag=$(push_approved_flag)

  if [ ! -f "$flag" ]; then
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  current_head=$(git rev-parse HEAD 2>/dev/null || echo "")
  if [ -z "$current_head" ] || [ "$(cat "$flag")" != "$current_head" ]; then
    echo "${message}。承認後に HEAD が変わったため再承認が必要です" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  # 承認の失効条件は「HEAD が remote に到達した」か「TTL 超過」であり、guard 通過
  # 時点では消費しない。旧実装は許可した瞬間に rm していたため、その後の pre-push
  # hook（unittest / validator / 依存不足）で push が落ちると承認だけが消えて
  # 再承認ループになった（2026-08-29）。push が成功すると remote-tracking ref が
  # 同じ HEAD を指すので、同一 HEAD の 2 度目の承認利用は自然に閉じる。
  ttl="${PUSH_APPROVAL_TTL_SECONDS:-1800}"
  # GNU stat（Linux / CI）を先に試す。逆順だと GNU の `stat -f %m` はファイルシステム情報を
  # 「成功」で返すため fallback に落ちず、算術式が壊れる（CI で実際に発生）。
  flag_mtime=$(stat -c %Y "$flag" 2>/dev/null || stat -f %m "$flag" 2>/dev/null || echo 0)
  flag_age=$(( $(date +%s) - flag_mtime ))
  if [ "$flag_age" -gt "$ttl" ]; then
    rm -f "$flag"
    echo "${message}。承認から ${ttl} 秒以上経過したため失効しました（再承認が必要です）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi
  if [ -n "$(git branch -r --contains "$current_head" 2>/dev/null)" ]; then
    rm -f "$flag"
    echo "${message}。この HEAD は既に remote に到達済みで承認は失効しました。別 ref へ push するなら再承認が必要です" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-push" "${COMMAND:-}" || true
    exit 2
  fi

  PUSH_APPROVAL_VERIFIED=1
}

# rule: gh-pr-merge-close
custom_gh_pr_merge_close() {
  # approve-pr で発行した承認（PR 番号 + TTL）と一致する、番号を明示した単独の
  # `gh pr merge|close <番号>` だけを許す。旧実装は無条件 deny で承認経路が無く、
  # ユーザーが merge を指示しても agent 側から実行する手段が無かった（2026-08-29）。
  # 検出パターンと deny メッセージは table（danger-rules.json）が SSOT。
  ere_matches "$NORMALIZED" "${ORIGIN}${ere}${WORD_END}" || return 0

  local flag pr_number approved_number flag_mtime flag_age ttl

  if ! _push_is_standalone "$NORMALIZED"; then
    echo "${message}。承認が適用されるのは単独の gh pr merge / close コマンドのみです（チェイン・subshell は対象外）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi

  # PR 番号は `gh pr merge 127` か PR URL（.../pull/127）の明示だけを受け付ける。
  # 番号省略（current branch の PR）は承認と対象の突き合わせができないので deny。
  pr_number=$(printf '%s' "$COMMAND" | perl -e '
local $/;
my $s = <STDIN>;
if ($s =~ /\bgh[ \t]+pr[ \t]+(?:merge|close)[ \t]+(?:--?[^ \t]+[ \t]+)*(?:\S*\/pull\/)?(\d+)\b/) { print $1 }
')
  if [ -z "$pr_number" ]; then
    echo "${message}。PR 番号を明示してください（gh pr merge <番号>）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi

  if ! review_gate_resolve_target_repo "$COMMAND"; then
    echo "${message}。承認の対象 repo を確定できません（${REVIEW_GATE_UNRESOLVABLE_REASON}）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi
  flag=$(pr_approved_flag)
  if [ ! -f "$flag" ]; then
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi

  ttl="${PR_APPROVAL_TTL_SECONDS:-1800}"
  flag_mtime=$(stat -c %Y "$flag" 2>/dev/null || stat -f %m "$flag" 2>/dev/null || echo 0)
  flag_age=$(( $(date +%s) - flag_mtime ))
  if [ "$flag_age" -gt "$ttl" ]; then
    rm -f "$flag"
    echo "${message}。承認から ${ttl} 秒以上経過したため失効しました（再承認が必要です）" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi

  approved_number=$(cat "$flag")
  if [ "$approved_number" != "$pr_number" ]; then
    echo "${message}。承認済みは PR #${approved_number} ですが、対象は #${pr_number} です" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-pr-merge-close" "${COMMAND:-}" || true
    exit 2
  fi

  PR_APPROVAL_VERIFIED=1
}

# rule: git-commit-chain
custom_git_commit_chain() {
  # git commit（チェイン/subshell 経由。deny リストはプレフィックスマッチのため && ; $( 経由が漏れる）
  if ere_matches "$NORMALIZED" "${CHAIN_ONLY_ORIGIN}(git|rtk git)[[:space:]]+commit"; then
    echo "git commit を他のコマンドとチェインしないでください。単独で実行してください" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-commit-chain" "${COMMAND:-}" || true
    exit 2
  fi
}

# rule: git-checkout-new-branch-in-main-repo
custom_git_checkout_new_branch_in_main_repo() {
  # git checkout -b / git switch -c をメインリポジトリでブロック（worktree では許可）
  if ere_matches "$NORMALIZED" "${ORIGIN}(git|rtk git)[[:space:]]+(checkout[[:space:]]+-[bB]|switch[[:space:]]+(-[cC]|--create))"; then
    GIT_TOP=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
    if [ -n "$GIT_TOP" ] && [ -d "$GIT_TOP/.git" ]; then
      cat >&2 <<'EOF'
メインリポジトリでブランチを作成しないでください。gwm で worktree を作成してから作業してください:

  gwm add <branch-name>            # 新規 worktree（main から）
  gwm add --from <base> <branch>   # base ref 指定
EOF
      declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-checkout-new-branch-in-main-repo" "${COMMAND:-}" || true
      exit 2
    fi
  fi
}

# rule: gh-api-comment-write
custom_gh_api_comment_write() {
  # gh api ... comment（書き込み系のみブロック。GET は許可）
  ere_matches "$NORMALIZED" "${ORIGIN}gh[[:space:]]+api" || return 0
  ere_matches "$NORMALIZED" '(-X|--method)[[:space:]]*(POST|PUT|PATCH|DELETE)|(^|[[:space:]])(-f|-F|--field|--raw-field|--input)[[:space:]]' || return 0

  # 'comment' は URL パスのセグメントに現れたときだけコメント API と見なす
  # （substring 一致だと comment-bot のようなラベル名を誤検知する）。
  if ere_matches "$NORMALIZED" '(^|[[:space:]])[^[:space:]]*/comments?([/?][^[:space:]]*)?([[:space:]]|$)'; then
    echo "PR へのコメント投稿はユーザーの明示的な許可を得てから実行してください" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-api-comment-write" "${COMMAND:-}" || true
    exit 2
  fi
  # graphql は URL パスを持たないため mutation 名で判定する（addComment 等）。
  # `query{...comments...}` は読み取りなので、`mutation` キーワードを伴うときだけ block する
  # （無名の `{...}` 短縮形は GraphQL 仕様上 query 固定）。
  if ere_matches "$NORMALIZED" "${ORIGIN}gh[[:space:]]+api[[:space:]]+graphql" && \
     ere_matches_nocase "$NORMALIZED" '(^|[^A-Za-z0-9_])mutation([^A-Za-z0-9_]|$)' && \
     ere_matches_nocase "$NORMALIZED" 'comment'; then
    echo "PR へのコメント投稿はユーザーの明示的な許可を得てから実行してください" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "gh-api-comment-write" "${COMMAND:-}" || true
    exit 2
  fi
}

# rule: git-no-verify
custom_git_no_verify() {
  # commit: --no-verify、または他の短縮フラグに混ざった -n も含めて block する。
  # commit 自身の引数だけを見る（$NORMALIZED は quote 内容が neutralize 済みで
  # 空白が保持されないため、コミットメッセージの中身を誤って引数として拾わない）。
  # perl の起動は commit を含むコマンドだけに限る（下の perl 正規表現が要求する
  # 語の部分集合なので判定結果は変わらない。Bash 呼び出し毎の fork を 1 つ減らす）。
  if ere_matches "$NORMALIZED" '(git|rtk[[:space:]]+git)[[:space:]]+commit' && \
     printf '%s' "$NORMALIZED" | perl -0777 -ne '
my $s = $_;
my $blocked = 0;
while ($s =~ /(?:git|rtk[ \t]+git)[ \t]+commit\b((?:[ \t]+[^ \t\n;&|]+)*)/g) {
    my $args = defined $1 ? $1 : "";
    for my $tok (split /[ \t]+/, $args) {
        next unless length $tok;
        if ($tok eq "--no-verify" || $tok =~ /^-[A-Za-z]*n[A-Za-z]*$/) { $blocked = 1; last; }
    }
    last if $blocked;
}
exit($blocked ? 0 : 1);
'; then
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-no-verify" "${COMMAND:-}" || true
    exit 2
  fi

  # push: --no-verify のみ対象（push の -n は --dry-run であり skip-hooks ではない）。
  if ere_matches "$NORMALIZED" "${ORIGIN}(git|rtk git)[[:space:]]+push" && \
     ere_matches "$NORMALIZED" '--no-verify([^A-Za-z0-9_]|$)'; then
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "git-no-verify" "${COMMAND:-}" || true
    exit 2
  fi
}

# rule: codex-companion-sandbox
custom_codex_companion_sandbox() {
  # sandbox 内実行だと sqlite state runtime の初期化に失敗することが実測済み
  # （codex-review-reminder 系のエラーシグネチャ参照）。dangerouslyDisableSandbox
  # が明示されていない実行だけを block する。
  #
  # substring マッチだと `rg codex-companion.mjs` / `cat codex-companion.mjs` の
  # ような閲覧系コマンドの引数を誤検知し、`codex --profile p app-server` の
  # ようにグローバルオプションを挟む形を見逃す。実行位置（origin）でマッチさせる:
  #   (a) node ... codex-companion.mjs の実行
  #   (b) コマンド語としての codex に、値ありなしのグローバルオプションを挟んで
  #       app-server サブコマンドが続く形
  local hit=0

  if ere_matches "$NORMALIZED" "${ORIGIN}node[[:space:]]+[^;&|]*codex-companion\\.mjs"; then
    hit=1
  fi

  # perl の起動は app-server を含むコマンドだけに限る（perl 側が exit 0 を返す条件に
  # app-server トークンが必須なので判定結果は変わらない。fork を 1 つ減らす）。
  if [ "$hit" -eq 0 ] && ere_matches "$NORMALIZED" 'app-server' && printf '%s' "$NORMALIZED" | perl -e '
my $origin = qr/(?:^|\||&&|;|\$\()\s*/;
local $/;
my $s = <STDIN>;
while ($s =~ /${origin}codex\b([^;&|\n]*)/g) {
    my @tokens = grep { length } split /\s+/, $1;
    my $i = 0;
    while ($i < @tokens) {
        my $tok = $tokens[$i];
        if ($tok =~ /^-/) {
            # 次のトークンが app-server 自身でも -- で始まってもいなければ、
            # そのフラグの値とみなして一緒に読み飛ばす（例: --profile p）。
            if ($i + 1 < @tokens && $tokens[$i + 1] ne "app-server" && $tokens[$i + 1] !~ /^-/) {
                $i += 2;
            } else {
                $i += 1;
            }
            next;
        }
        exit(0) if $tok eq "app-server";
        last;
    }
}
exit 1
'; then
    hit=1
  fi

  if [ "$hit" -eq 1 ] && [ "$DANGEROUSLY_DISABLE_SANDBOX" != "true" ]; then
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "codex-companion-sandbox" "${COMMAND:-}" || true
    exit 2
  fi
}

if [ "$_BLOCK_DANGEROUS_SOURCED" -eq 0 ]; then
# --- 実効ルール（$TABLE_ROWS、table 読み込み時に選別済み）を評価順（rules 配列順）に走査する ---
while IFS="$FIELD_SEP" read -r row_tag rule_id impl ere origin_kind word_end action message; do
  # 実効 rule が 0 件のときの空行（here-string は最低 1 行を渡す）は R タグを持たない。
  # 空 ere は全コマンドに一致するので、R 行以外は rule として評価しない。
  [ "$row_tag" = "R" ] || continue
  if [ "$impl" = "custom" ]; then
    fn="custom_${rule_id//-/_}"
    if ! declare -f "$fn" >/dev/null 2>&1; then
      echo "危険コマンドルール table の custom rule に対応する実装がありません: ${rule_id}（安全側に倒してブロックします）" >&2
      declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "$rule_id" "${COMMAND:-}" || true
      exit 2
    fi
    "$fn"
    continue
  fi

  case "$origin_kind" in
    default) origin_pattern="$ORIGIN" ;;
    chain-only) origin_pattern="$CHAIN_ONLY_ORIGIN" ;;
    *) origin_pattern="" ;;
  esac
  if [ "$word_end" = "true" ]; then
    word_end_pattern="$WORD_END"
  else
    word_end_pattern=""
  fi

  if ere_matches "$NORMALIZED" "${origin_pattern}${ere}${word_end_pattern}"; then
    if [ "$action" = "warn" ]; then
      # warn で即 exit 0 すると後続の block ルールを評価せずコマンド全体を
      # 許可してしまう（例: `git rebase x && doc2notion init` は git-rebase の
      # warn が先に一致して破壊的 init が素通り）。warn は蓄積だけして走査を
      # 続け、block が 1 件も無かった場合にループ後で返す。
      if [ -z "${WARN_MESSAGE:-}" ]; then
        WARN_MESSAGE="$message"
      fi
      continue
    fi
    # block（および想定外の action は安全側に倒してブロック扱い）
    echo "$message" >&2
    declare -f record_denial >/dev/null 2>&1 && record_denial "block-dangerous-in-bash" "$rule_id" "${COMMAND:-}" || true
    exit 2
  fi
done <<< "$TABLE_ROWS"

# 全ルール走査で block が無かった場合のみ warn を返す。push 承認の通知
# （検証は custom_git_push 内で済んでいる）と同時成立し得るため 1 本に束ねる。
ADDITIONAL_CONTEXT="${WARN_MESSAGE:-}"
if [ -n "${PUSH_APPROVAL_VERIFIED:-}" ]; then
  if [ -n "$ADDITIONAL_CONTEXT" ]; then
    ADDITIONAL_CONTEXT="${ADDITIONAL_CONTEXT}（push 承認を確認しました。HEAD が remote に到達した時点で失効）"
  else
    ADDITIONAL_CONTEXT="push 承認を確認しました（HEAD が remote に到達した時点で失効）"
  fi
fi
if [ -n "${PR_APPROVAL_VERIFIED:-}" ]; then
  if [ -n "$ADDITIONAL_CONTEXT" ]; then
    ADDITIONAL_CONTEXT="${ADDITIONAL_CONTEXT}（PR 承認を確認しました）"
  else
    ADDITIONAL_CONTEXT="PR 承認を確認しました（approve-pr の番号と一致）"
  fi
fi
if [ -n "$ADDITIONAL_CONTEXT" ]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"%s"}}\n' "$ADDITIONAL_CONTEXT"
fi

exit 0
fi # _BLOCK_DANGEROUS_SOURCED（main loop）

#!/usr/bin/env bash
# 導入済みの安全ガード（Claude Code の PreToolUse hook）に、見本の操作を流して効き目を確かめる。
#
#   scripts/try.sh [claude] [--dest DIR]
#
# 使い捨ての git repo を作り、hook に「この操作をしてよいか」だけを問い合わせる。
# 見本の操作そのものは実行しない。期待どおりの判定（通過 / 拒否 / 確認）を、期待どおりの
# hook が出したら OK、違えば NG を表示し、NG が 1 件でもあれば exit 1。未対応の target は exit 2。
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_NAME="install-manifest.json"

TARGET=""
DEST_OVERRIDE=""

usage() {
  echo "Usage: $0 [claude] [--dest DIR]"
  echo "  claude     確かめる target（現在は Claude Code のみ対応。省略時も claude）"
  echo "  --dest     install.sh --dest で入れた場合の導入先"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dest)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      DEST_OVERRIDE="$1"
      ;;
    --help|-h) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *)
      [ -z "$TARGET" ] || { usage >&2; exit 2; }
      TARGET="$1"
      ;;
  esac
  shift
done
TARGET="${TARGET:-claude}"

manifest="$REPO_ROOT/$TARGET/$MANIFEST_NAME"
if [ "$TARGET" != "claude" ] || [ ! -f "$manifest" ]; then
  echo "エラー: try.sh は現在 claude だけに対応しています（'$TARGET' は未対応）。" >&2
  echo "導入状態の確認は scripts/doctor.sh を使ってください。" >&2
  exit 2
fi
for cmd in jq git; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "エラー: $cmd が必要です" >&2; exit 2; }
done

config_dir="$(jq -r '.configDir' "$manifest")"
dest="$DEST_OVERRIDE"
if [ -z "$dest" ]; then
  config_dir_env="$(jq -r '.configDirEnv // empty' "$manifest")"
  if [ -n "$config_dir_env" ] && [ -n "${!config_dir_env:-}" ]; then
    dest="${!config_dir_env}"
  else
    dest="$HOME/${config_dir#\~/}"
  fi
fi
settings="$dest/settings.json"
if [ ! -f "$settings" ]; then
  echo "エラー: $settings がありません。先に scripts/setup.sh か scripts/install.sh claude を実行してください。" >&2
  exit 2
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/harunon-try.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# hook は ~/.claude/... を command と内部の両方で参照する。--dest で入れた場合は、
# 一時 HOME の .claude を導入先に向けて、実際の ~/.claude を混ぜずに判定させる
hook_home="$HOME"
if [ -n "$DEST_OVERRIDE" ]; then
  hook_home="$work/home"
  mkdir -p "$hook_home"
  ln -s "$(cd "$dest" && pwd)" "$hook_home/${config_dir#\~/}"
fi

# Claude Code は settings.json の env を hook に渡す（HARNESS_RUNTIME 等）。同じものを渡す。
# 見本の拒否が利用者の拒否ログに混ざらないよう、記録先は一時ディレクトリにする。
# 見本の repo は一時ディレクトリにあるので、/tmp 配下を素通しする main 編集ガードの例外も外す。
hook_env=(HOME="$hook_home" HARNESS_DENIAL_LOG="$work/denials.jsonl" CLAUDE_HOOK_ALLOW_TMP_PATHS=1)
while IFS= read -r -d '' pair; do
  hook_env+=("$pair")
done < <(jq -j '(.env // {}) | to_entries[] | "\(.key)=\(.value)\u0000"' "$settings")

new_repo() {
  git init -q "$1"
  git -C "$1" symbolic-ref HEAD "refs/heads/$2"  # git init -b は git 2.28 以上が要る
  git -C "$1" -c user.name=try -c user.email=try@example.com -c commit.gpgsign=false \
    -c core.hooksPath=/dev/null commit -q --allow-empty -m init
}
repo="$work/repo"
new_repo "$repo" feature
git -C "$repo" remote add origin https://github.com/example/example.git
echo "sample" > "$repo/sample.txt"
git -C "$repo" add sample.txt
# main branch を直接編集する見本用（作業 branch の repo とは別に置く）
main_repo="$work/main-repo"
new_repo "$main_repo" main
echo "a" > "$main_repo/notes.txt"

hook_name() {
  local token
  for token in $1; do
    case "$token" in */*) basename "$token"; return 0 ;; esac
  done
  printf '%s' "$1"
}

# 1 つの操作を、tool 名に matcher が合う PreToolUse hook すべてに問い合わせる。
# 拒否・確認した hook ごとに「判定<TAB>hook 名<TAB>理由」を 1 行ずつ出す。
decide() {
  local tool="$1" input="$2" cwd="$3" payload hooks hook_cmd rc decision reason
  payload="$(jq -nc --arg tool "$tool" --argjson input "$input" --arg cwd "$cwd" \
    '{hook_event_name: "PreToolUse", session_id: "harunon-try", tool_name: $tool, tool_input: $input, cwd: $cwd}')"
  # matcher が空・"*"・無しなら全 tool に合う（Claude Code と同じ）
  if ! hooks="$(jq -r --arg tool "$tool" '
      .hooks.PreToolUse[]?
      | ((.matcher // "") as $m | select($m == "" or $m == "*" or ($tool | test("^(" + $m + ")$"))))
      | .hooks[]? | select(.type == "command") | .command' "$settings")"; then
    echo "エラー: $settings の PreToolUse を読めません" >&2
    exit 2
  fi
  while IFS= read -r hook_cmd; do
    [ -n "$hook_cmd" ] || continue
    set +e
    (cd "$cwd" && printf '%s' "$payload" | env "${hook_env[@]}" sh -c "$hook_cmd" >"$work/out" 2>"$work/err")
    rc=$?
    set -e
    if [ "$rc" -eq 2 ]; then
      decision="deny"
      reason="$(cat "$work/err")"
    else
      decision="$(jq -r '.hookSpecificOutput.permissionDecision // empty' "$work/out" 2>/dev/null || true)"
      reason="$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' "$work/out" 2>/dev/null || true)"
    fi
    case "$decision" in
      deny|ask)
        printf '%s\t%s\t%s\n' "$decision" "$(hook_name "$hook_cmd")" "$(printf '%s' "$reason" | tr '\n\t' '  ' | cut -c1-160)"
        ;;
    esac
  done <<< "$hooks"
}

label() {
  case "$1" in
    allow) echo "通過" ;;
    deny) echo "拒否" ;;
    ask) echo "確認" ;;
  esac
}

failed=0
tab="$(printf '\t')"
# check <見出し> <期待する判定（空白区切り）> <止めるはずの hook（空白区切り、無ければ ""）> <tool> <input> [cwd]
check() {
  local title="$1" expected="$2" guards="$3" tool="$4" input="$5" cwd="${6:-$repo}"
  local results decision mark guard by="" line_decision line_hook line_reason
  results="$(decide "$tool" "$input" "$cwd")"
  # 複数の hook が答えたら、Claude Code と同じく拒否 > 確認 > 通過で決める
  decision="allow"
  if printf '%s\n' "$results" | grep -q '^ask'; then decision="ask"; fi
  if printf '%s\n' "$results" | grep -q '^deny'; then decision="deny"; fi
  mark="OK"
  case " $expected " in
    *" $decision "*) ;;
    *) mark="NG" ;;
  esac
  if [ "$mark" = "OK" ] && [ -n "$guards" ]; then
    for guard in $guards; do
      if printf '%s\n' "$results" | grep -q "^$decision$tab$guard$tab"; then by="$guard"; fi
    done
    [ -n "$by" ] || mark="NG"
  fi
  [ "$mark" = "OK" ] || failed=1
  printf '  [%s] %s → %s\n' "$mark" "$title" "$(label "$decision")"
  [ -z "$guards" ] || [ -n "$by" ] || printf '        止めるはずの hook: %s\n' "$guards"
  while IFS="$tab" read -r line_decision line_hook line_reason; do
    [ -n "$line_decision" ] || continue
    printf '        %s（%s）: %s\n' "$(label "$line_decision")" "$line_hook" "$line_reason"
  done <<< "$results"
  return 0
}

bash_input() {
  jq -nc --arg c "$1" '{command: $c}'
}

edit_input() {
  jq -nc --arg p "$1" '{file_path: $p, old_string: "a", new_string: "b"}'
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  harunon-slim try: 安全ガードの効き目を確かめる"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "対象: $settings"
echo "見本の操作は実行せず、hook の判定だけを表示します。"
echo ""
echo "▼ 普段の操作（通過するはず）"
check "git status" "allow" "" Bash "$(bash_input "git status")"
check "git commit -m 'add sample'" "allow" "" Bash "$(bash_input "git commit -m 'add sample'")"
check "作業 branch のファイルを編集" "allow" "" Edit "$(edit_input "$repo/sample.txt")"
echo ""
echo "▼ 危ない操作（止まるはず）"
check "hook を飛ばす commit（--no-verify）" "deny" "block-dangerous-in-bash.sh" Bash "$(bash_input "git commit --no-verify -m skip")"
check "承認なしの force push" "deny ask" "block-dangerous-in-bash.sh" Bash "$(bash_input "git push --force origin main")"
check "本文を書かずに PR 作成（--fill）" "deny" "block-japanese-tech-writing.sh harness-publication-gate.sh" Bash "$(bash_input "gh pr create --fill")"
check "main branch のファイルを直接編集" "deny" "block-edit-on-main.sh" Edit "$(edit_input "$main_repo/notes.txt")" "$main_repo"

echo ""
if [ "$failed" -eq 0 ]; then
  echo "✓ すべて期待どおりに判定されました。"
else
  echo "✗ 期待と違う判定があります（NG の行）。scripts/doctor.sh claude で導入状態を確認してください。"
fi
exit "$failed"

#!/usr/bin/env bash
# 公開 slim 配布物（harunon-harness-slim / harunon-pi-agent-slim）を SSOT から生成し、
# 配布先 repo と同じ条件で検証してから push する。CI（.github/workflows/publish-slim.yml）と
# ローカルで同じ実装を使う。
#
#   publish-public-slim.sh [verify|publish] [options]
#
#   verify   (既定) build → 生成物の中で配布先の CI と同じ検査を回す
#   publish  verify のあと、manifest の publish 宣言に従って各 repo へ push する
#
#   --output DIR       生成先（既定: $RUNNER_TEMP/public-slim、無ければ <repo>/build/public-slim）。
#                      /tmp 配下は避ける（block-edit-on-main.sh が /tmp をバイパスするため、
#                      そこで検証すると main 直編集ガードの不具合を見逃す）
#   --env-file PATH    ゲートの BLOCKED_TERMS を読む env file（既定: <repo>/.env）。
#                      環境変数 BLOCKED_TERMS があれば一時 env file を作って渡す（CI 用）
#   --remote-base DIR  publish 先を GitHub ではなく DIR/<owner>/<repo>.git のローカル bare repo にする（テスト用）
#   --dry-run          publish: 差分だけ表示して commit / push しない
#   --skip-verify      publish: verify を飛ばす（テスト・CI 内部用。人手では使わない）
#
# 認証: SLIM_DEPLOY_TOKEN があれば https://x-access-token:<token>@github.com/... で clone / push する
# （URL は表示しない）。無ければ素の https URL でローカルの credential helper に任せる。
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/packages/public-slim/manifest.json"
HARNESS_SLIM_DIR="harunon-harness-slim"
PI_AGENT_SLIM_DIR="harunon-pi-agent-slim"
COMMIT_NAME="harunon-harness publish"
COMMIT_EMAIL="harunon-harness-publish@users.noreply.github.com"

MODE="verify"
OUTPUT=""
ENV_FILE=""
REMOTE_BASE=""
DRY_RUN=0
SKIP_VERIFY=0

usage() {
  perl -ne 'print if 2..24' "${BASH_SOURCE[0]}" | perl -pe 's/^# ?//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    verify|publish) MODE="$1" ;;
    --output) shift; [ "$#" -gt 0 ] || { usage >&2; exit 2; }; OUTPUT="$1" ;;
    --env-file) shift; [ "$#" -gt 0 ] || { usage >&2; exit 2; }; ENV_FILE="$1" ;;
    --remote-base) shift; [ "$#" -gt 0 ] || { usage >&2; exit 2; }; REMOTE_BASE="$1" ;;
    --dry-run) DRY_RUN=1 ;;
    --skip-verify) SKIP_VERIFY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# --- 前提ツール ---------------------------------------------------------------

# Python は mise 管理を優先し、mise が無い環境（GitHub Actions）では PATH の python3 を使う。
if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v mise >/dev/null 2>&1 && PYTHON_BIN="$(cd "$REPO_ROOT" && mise which python3 2>/dev/null)"; then
    :
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
fi
[ -x "${PYTHON_BIN:-}" ] || { echo "python3 が見つかりません（PYTHON_BIN で指定可）" >&2; exit 2; }
for tool in git rsync jq node; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required" >&2; exit 2; }
done

if [ -z "$OUTPUT" ]; then
  if [ -n "${RUNNER_TEMP:-}" ]; then
    OUTPUT="$RUNNER_TEMP/public-slim"
  else
    OUTPUT="$REPO_ROOT/build/public-slim"
  fi
fi
case "$OUTPUT" in
  /tmp/*|/private/tmp/*)
    echo "warning: --output が /tmp 配下です。block-edit-on-main.sh は /tmp をバイパスするため main 直編集ガードの検証が効きません" >&2
    ;;
esac
mkdir -p "$OUTPUT"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/publish-public-slim.XXXXXX")"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

STEP=""
step() {
  STEP="$1"
  printf '\n==> %s\n' "$1"
}
fail() {
  printf '\nFAILED at step: %s\n' "$STEP" >&2
  exit 1
}
trap 'fail' ERR

# --- ゲートの env file ---------------------------------------------------------
# .env は追跡外なので CI には無い。BLOCKED_TERMS を secret で受け取り一時 env file にする。
# 値は一切表示しない。どちらも無ければ builder が fail-close（exit 2）で止まる。
if [ -z "$ENV_FILE" ] && [ -n "${BLOCKED_TERMS:-}" ]; then
  ENV_FILE="$SCRATCH/gate.env"
  umask 077
  printf 'BLOCKED_TERMS=%s\n' "$BLOCKED_TERMS" > "$ENV_FILE"
  umask 022
fi
BUILD_ARGS=(--output "$OUTPUT")
[ -n "$ENV_FILE" ] && BUILD_ARGS+=(--env-file "$ENV_FILE")

# --- verify --------------------------------------------------------------------

verify() {
  step "build: scripts/build-public-slim.py"
  if ! "$PYTHON_BIN" "$REPO_ROOT/scripts/build-public-slim.py" "${BUILD_ARGS[@]}"; then
    echo "build / gate が失敗しました（BLOCKED_TERMS 未設定なら .env か環境変数 BLOCKED_TERMS を用意する）" >&2
    return 1
  fi

  # 配布先の CI と同じ条件: 別マシンの HOME（空）、main ブランチの checkout、/tmp 外のパス。
  local verify_home slim pi dest
  verify_home="$SCRATCH/home"
  mkdir -p "$verify_home"
  # HOME を差し替えても mise は実 HOME のデータを使わせる（無いと pre-push hook 系のテストが
  # 「mise が Python を解決できない」で落ちる。CI には mise が無いので影響しない）。
  if command -v mise >/dev/null 2>&1; then
    export MISE_DATA_DIR="${MISE_DATA_DIR:-$HOME/.local/share/mise}"
    export MISE_CONFIG_DIR="${MISE_CONFIG_DIR:-$HOME/.config/mise}"
    export MISE_STATE_DIR="${MISE_STATE_DIR:-$HOME/.local/state/mise}"
    if [ -z "${MISE_CACHE_DIR:-}" ]; then
      if [ -d "$HOME/Library/Caches/mise" ]; then
        export MISE_CACHE_DIR="$HOME/Library/Caches/mise"
      else
        export MISE_CACHE_DIR="$HOME/.cache/mise"
      fi
    fi
  fi
  slim="$OUTPUT/$HARNESS_SLIM_DIR"
  pi="$OUTPUT/$PI_AGENT_SLIM_DIR"

  step "harness-slim: git init on main（tests need HEAD）"
  git -C "$slim" init -q -b main
  git -C "$slim" add -A
  git -C "$slim" -c user.name="$COMMIT_NAME" -c user.email="$COMMIT_EMAIL" commit -q -m "verify snapshot"

  step "harness-slim: node --test"
  (cd "$slim" && HOME="$verify_home" node --test "scripts/tests/node/*.test.ts" >/dev/null)

  step "harness-slim: validate-harness.py"
  HOME="$verify_home" "$PYTHON_BIN" "$slim/scripts/validate-harness.py"

  step "harness-slim: distribute.py <target> --list"
  local config target
  for config in "$slim"/packages/targets/*/config.json; do
    target="$(basename "$(dirname "$config")")"
    HOME="$verify_home" "$PYTHON_BIN" "$slim/scripts/distribute.py" "$target" --list >/dev/null
  done

  step "harness-slim: shellcheck"
  if command -v shellcheck >/dev/null 2>&1; then
    (cd "$slim" && shellcheck -S warning packages/core/hooks/*.sh packages/core/hooks/lib/*.sh \
      packages/runtimes/opencode-launcher/opencode scripts/*.sh .githooks/pre-commit .githooks/pre-push)
  else
    echo "shellcheck not installed; skipped"
  fi

  step "harness-slim: run-tests.py"
  HOME="$verify_home" "$PYTHON_BIN" "$slim/scripts/run-tests.py"

  step "pi-agent-slim: validate.sh"
  (cd "$pi" && HOME="$verify_home" ./scripts/validate.sh)

  step "pi-agent-slim: install.sh --dry-run（書き込みなし）"
  dest="$SCRATCH/pi-dest"
  (cd "$pi" && HOME="$verify_home" ./scripts/install.sh --dest "$dest" --dry-run >/dev/null)
  if [ -e "$dest" ]; then
    echo "--dry-run が dest を作成しました: $dest" >&2
    return 1
  fi

  step "pi-agent-slim: install.sh → --check"
  (cd "$pi" && HOME="$verify_home" ./scripts/install.sh --dest "$dest" >/dev/null)
  (cd "$pi" && HOME="$verify_home" ./scripts/install.sh --dest "$dest" --check)

  step "verify: all steps passed"
  printf '  output: %s\n' "$OUTPUT"
}

# --- publish -------------------------------------------------------------------

publish_target_url() {
  # 引数: owner/repo。REMOTE_BASE があればローカル bare、無ければ GitHub（token 付きは表示しない）
  local repo="$1"
  if [ -n "$REMOTE_BASE" ]; then
    printf '%s/%s.git' "$REMOTE_BASE" "$repo"
  elif [ -n "${SLIM_DEPLOY_TOKEN:-}" ]; then
    printf 'https://x-access-token:%s@github.com/%s.git' "$SLIM_DEPLOY_TOKEN" "$repo"
  else
    printf 'https://github.com/%s.git' "$repo"
  fi
}

publish_one() {
  local name="$1" repo="$2" branch="$3"
  local src="$OUTPUT/$name" work="$SCRATCH/publish/$name" url
  [ -d "$src" ] || { echo "生成物が無い: $src" >&2; return 1; }
  url="$(publish_target_url "$repo")"

  step "publish: $name → $repo ($branch)"
  mkdir -p "$work"
  git -C "$work" init -q -b "$branch"
  # URL に token が入り得るので remote には登録せず、fetch / push の引数でだけ使う
  if git -C "$work" fetch -q --depth 1 "$url" "$branch" 2>/dev/null; then
    git -C "$work" checkout -q -B "$branch" FETCH_HEAD
  else
    echo "  remote に $branch が無いか空 repo のため、新規ブランチとして push します"
  fi

  # -c: 内容で比較する。checkout 直後のファイルと生成物が同サイズ・同秒 mtime だと
  # 既定の quick check が「同じ」と判定して更新を落とす
  rsync -ac --delete --exclude .git "$src/" "$work/"
  git -C "$work" add -A
  if git -C "$work" diff --cached --quiet; then
    echo "  no changes; skip"
    return 0
  fi
  git -C "$work" diff --cached --stat | tail -20
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  dry-run; commit / push しない"
    return 0
  fi

  local sha src_branch
  sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
  src_branch="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
  git -C "$work" -c user.name="$COMMIT_NAME" -c user.email="$COMMIT_EMAIL" commit -q \
    -m "Regenerate from harunon-harness@$sha ($src_branch)" \
    -m "Generated by scripts/publish-public-slim.sh. Do not edit here; changes belong in the SSOT."
  GIT_TERMINAL_PROMPT=0 git -C "$work" push -q "$url" "HEAD:refs/heads/$branch"
  echo "  pushed $(git -C "$work" rev-parse --short HEAD)"
}

publish() {
  if [ "$SKIP_VERIFY" -eq 1 ]; then
    echo "--skip-verify: 生成・検証を飛ばし、$OUTPUT の内容をそのまま publish します"
  else
    verify
  fi

  # 出力ディレクトリ → 配布先 repo の対応は manifest の publish 宣言だけが持つ
  local dir name repo branch
  for dir in "$OUTPUT"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    repo="$(jq -r --arg n "$name" '.publish[$n].repo // empty' "$MANIFEST")"
    branch="$(jq -r --arg n "$name" '.publish[$n].branch // empty' "$MANIFEST")"
    if [ -z "$repo" ] || [ -z "$branch" ]; then
      echo "manifest の publish に ${name} の宣言が無い（${MANIFEST}）" >&2
      return 1
    fi
    publish_one "$name" "$repo" "$branch"
  done
  step "publish: done"
}

case "$MODE" in
  verify) verify ;;
  publish) publish ;;
esac

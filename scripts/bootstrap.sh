#!/usr/bin/env bash
# bootstrap.sh — runtime + shared-agents artifact の同期エントリポイント
#
# モード:
#   --push   (default)  packages/core + extras を各 AI ツール設定ディレクトリに配布
#   --check             live と harness の drift を検出（書き込まない）
#   --pull              live 側の手元修正を harness 側 source に還流
#
# 実行例:
#   ./scripts/bootstrap.sh                          # 全ターゲットに push
#   ./scripts/bootstrap.sh --check                  # 全ターゲットの drift 確認のみ
#   ./scripts/bootstrap.sh --pull                   # 全ターゲットから harness に取り込み
#   ./scripts/bootstrap.sh --targets claude         # 特定ターゲットのみ
#   ./scripts/bootstrap.sh --targets claude,opencode
#   ./scripts/bootstrap.sh --dry-run                # 何が起きるか表示のみ
#   ./scripts/bootstrap.sh --skip-submodule         # extras submodule の init/update をスキップ
#   ./scripts/bootstrap.sh --core-only              # extras 未取得でも core のみで続行（fail-close の明示オプトイン）
#
# 環境変数:
#   CLAUDE_DIR  claude target の配布先を override（互換用。指定時のみ有効）
#
# 初回 codex push 時、packages/targets/codex/config.local.toml が無ければ対話生成する（gitignore 済）。
# 初回 push 時、.env が無ければ対話生成する（gitignore 済。非対話実行時は WARN してスキップ）。
# extras（packages/extras/_active）は private な git submodule。未取得時はデフォルトで fail-close する。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Tests and callers may provide an explicit interpreter. Otherwise resolve the
# project-managed Python from mise.toml; never fall back to system python3.
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if ! command -v mise > /dev/null 2>&1; then
    printf 'ERROR: mise が見つかりません。Python は mise 管理の3.14を使用します。\n' >&2
    exit 1
  fi
  PYTHON_BIN="$(cd "$REPO_ROOT" && mise which python3)"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'ERROR: mise 管理のPython 3.14が見つかりません: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

DEFAULT_TARGETS="shared-agents claude codex opencode opencode-launcher pi omp"
TARGETS=""
MODE="push"
DRY_RUN_FLAG=""
SKIP_SUBMODULE=false
CORE_ONLY=false

# --- args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --push|--check|--pull)
      MODE="${1#--}"
      shift
      ;;
    --dry-run)
      DRY_RUN_FLAG="--dry-run"
      shift
      ;;
    --targets)
      TARGETS="$(echo "$2" | tr ',' ' ')"
      shift 2
      ;;
    --targets=*)
      TARGETS="$(echo "${1#--targets=}" | tr ',' ' ')"
      shift
      ;;
    --skip-submodule)
      SKIP_SUBMODULE=true
      shift
      ;;
    --core-only)
      CORE_ONLY=true
      shift
      ;;
    -h|--help)
      sed -n '2,24p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$TARGETS" ]]; then
  TARGETS="$DEFAULT_TARGETS"
fi

# --- helpers ---
banner(){ printf '\n━━━ %s ━━━\n' "$1"; }
info()  { printf '  → %s\n' "$1"; }
ok()    { printf '  ✓ %s\n' "$1"; }
skip()  { printf '  ⊘ %s\n' "$1"; }
warn()  { printf '  ⚠ %s\n' "$1"; }

# --- .env セットアップ（push のときだけ、初回のみ）---
# BLOCKED_TERMS（.githooks/pre-commit が参照する禁止語リスト）を対話生成する。
# 非対話実行（CI/cron）では書き込まず WARN のみで続行する（fail-open。secrets ではないため安全）。
setup_env_file() {
  local env_file="$REPO_ROOT/.env"

  if [[ -f "$env_file" ]]; then
    return 0
  fi

  if [[ -n "$DRY_RUN_FLAG" ]] || ! [ -t 0 ]; then
    warn ".env が見つかりません（非対話のためスキップ）。'cp .env.example .env' で手動作成するか、対話実行で生成してください"
    return 0
  fi

  banner ".env セットアップ（初回のみ）"
  info ".env が存在しません。BLOCKED_TERMS（禁止語。pre-commit hook が参照）を設定します。"
  local ans_terms=""
  read -r -p "  BLOCKED_TERMS をカンマ区切りで入力（空 Enter でスキップ）: " ans_terms

  {
    printf '# 個人/会社固有のコードネーム。pre-commit hook が staged 内容/ファイル名から検出した場合 commit を block する。\n'
    printf 'BLOCKED_TERMS=%s\n' "$ans_terms"
  } > "$env_file"
  ok ".env を作成しました: $env_file"
}

# .env が .gitignore に含まれているか確認し、無ければ追記する。
ensure_env_gitignored() {
  local gitignore="$REPO_ROOT/.gitignore"

  if [[ -f "$gitignore" ]] && grep -qxF '.env' "$gitignore"; then
    return 0
  fi

  if [[ -n "$DRY_RUN_FLAG" ]]; then
    info "dry-run: would ensure .env is in .gitignore"
    return 0
  fi

  printf '.env\n' >> "$gitignore"
  ok ".gitignore に .env を追記しました（追跡対象になることを防止）"
}

if [[ "$MODE" == "push" ]]; then
  setup_env_file
  ensure_env_gitignored
fi

# --- Step 1: extras 解決（push のときだけ）---
# extras は private な git submodule（packages/extras/_active、.gitmodules 上は gitlink 160000）。
# 取得元 URL はここに持たない（.gitmodules の宣言が唯一の真実）。宣言そのものが無い配布
# （extras を含めない slim 等）では fail-close せず skip する。fail-close するのは
# 「宣言されているのに未取得」のときだけ。
if [[ "$MODE" == "push" ]]; then
  banner "Step 1: extras"
  extras="$REPO_ROOT/packages/extras/_active"
  extras_declared=""
  if [[ -f "$REPO_ROOT/.gitmodules" ]]; then
    extras_declared="$(git -C "$REPO_ROOT" config --file "$REPO_ROOT/.gitmodules" \
      --get "submodule.packages/extras/_active.path" 2>/dev/null || true)"
  fi
  if $SKIP_SUBMODULE; then
    skip "--skip-submodule 指定"
  elif [[ -d "$extras" ]]; then
    ok "extras 利用可能 ($(cd "$extras" && pwd -P))"
  elif [[ -z "$extras_declared" ]]; then
    skip "extras は宣言されていない。core のみで配布を続行"
  elif $CORE_ONLY; then
    skip "extras が見つからない。core のみで配布を続行（--core-only 指定）"
  else
    echo "ERROR: extras が見つからない（private submodule 未取得）" >&2
    echo "  取得: git submodule update --init packages/extras/_active" >&2
    echo "  core のみで続行するには --core-only を指定してください" >&2
    exit 1
  fi
fi

# --- Step 1.5: global mise env 確認（report-only、push/check どちらでも実行） ---
# mise.global.example.toml の [env] と live の ~/.config/mise/config.toml のドリフトを
# 警告するだけ。反映は setup-machine.sh の責務なので、ここでは適用も失敗もしない。
banner "Step 1.5: global mise env 確認"
set +e
mise_env_output="$("$PYTHON_BIN" "$REPO_ROOT/scripts/mise-global-check.py" 2>&1)"
mise_env_rc=$?
set -e
case "$mise_env_rc" in
  0) ok "global mise: 宣言どおり" ;;
  1)
    warn "global mise の [env] が SSOT とズレています:"
    printf '%s\n' "$mise_env_output" | while IFS= read -r line; do warn "  $line"; done
    ;;
  *)
    warn "global mise env チェックが失敗しました (exit $mise_env_rc): $mise_env_output"
    ;;
esac

# --- codex local config セットアップ（push モードで codex が対象のときのみ） ---
# 初回 bootstrap 時に packages/targets/codex/config.local.toml を対話生成する。
# worktrees base は gwm の worktree_base_path を正とし、未設定時は手入力を促す。
setup_codex_local_config() {
  local local_cfg="$REPO_ROOT/packages/targets/codex/config.local.toml"

  # sandbox roots が既にあれば、既存の machine-local 設定を保持する。
  if [[ -f "$local_cfg" ]] && grep -q '^[[:space:]]*\[sandbox_workspace_write\]' "$local_cfg"; then
    return 0
  fi

  # 非対話（CI/cron）または dry-run のときはスキップ
  if [[ -n "$DRY_RUN_FLAG" ]] || ! [ -t 0 ]; then
    skip "config.local.toml の sandbox roots 生成をスキップ（非対話。後で手動 or 対話 install で生成）"
    return 0
  fi

  banner "codex config.local.toml セットアップ（初回のみ）"
  info "config.local.toml がありません。マシン固有の writable_roots を設定します。"

  # gwm の worktree_base_path を解決する
  local gwm_cfg="$HOME/.config/gwm/config.toml"
  local default_worktrees=""
  if command -v gwm > /dev/null 2>&1 && [[ -f "$gwm_cfg" ]]; then
    default_worktrees="$(awk -F'=' '/^[[:space:]]*worktree_base_path/{gsub(/[" ]/,"",$2);print $2}' "$gwm_cfg")"
  fi

  if [[ -z "$default_worktrees" ]]; then
    info "gwm の worktree_base_path が取得できませんでした。"
    info "gwm は worktree_base_path を ~/.config/gwm/config.toml で管理します。"
    info "gwm 未設定の場合: (a) worktrees パスを手入力 (b) 'skip' と入力してスキップ"
    info "（gwm のインストール自体は bootstrap では行いません）"
  fi

  local default_git="$REPO_ROOT/.git"
  local ans_worktrees=""
  local ans_git=""

  # worktrees パスが確定するまでループ
  while true; do
    if [[ -n "$default_worktrees" ]]; then
      read -r -p "  worktrees パス [$default_worktrees]: " ans_worktrees
      ans_worktrees="${ans_worktrees:-$default_worktrees}"
    else
      read -r -p "  worktrees パス（'skip' でスキップ）: " ans_worktrees
    fi

    if [[ "$ans_worktrees" == "skip" ]]; then
      skip "config.local.toml の生成をスキップしました"
      return 0
    fi

    if [[ "$ans_worktrees" == /* ]]; then
      break
    fi

    info "絶対パスを入力するか 'skip' と入力してください。"
  done

  read -r -p "  harness .git パス [$default_git]: " ans_git
  ans_git="${ans_git:-$default_git}"

  # TOML の組み立ては heredoc ではなく専用スクリプトに任せる。入力パスの `"` / `\`
  # を素通しすると壊れた TOML を書いて成功表示まで進む。
  if ! "$PYTHON_BIN" "$REPO_ROOT/scripts/codex-local-config.py" "$local_cfg" "$ans_worktrees" "$ans_git" "$HOME"; then
    echo "ERROR: config.local.toml の sandbox roots を生成できませんでした" >&2
    exit 1
  fi
  ok "config.local.toml の sandbox roots を生成しました: $local_cfg"
}

if [[ "$MODE" == "push" ]]; then
  case " $TARGETS " in
    *" codex "*)
      setup_codex_local_config
      ;;
  esac
fi

# --- Step 1.9: harunon-core plugin を Codex へ配備（push で codex が対象のときのみ） ---
# plugins/cache と config.toml の [plugins.*] は Codex がアプリとして管理する領域なので、
# distribute.py のファイルコピーでは配らない（target config の対象外宣言はそのため）。
# 代わりに Codex 自身の CLI に入れさせる。marketplace add / plugin add はどちらも冪等で、
# 既に入っていれば "already added" を返して上書き更新する。
#
# fail-closed にしない理由: これは guard の配備であって配布物の整合ではない。Codex 未導入の
# マシンや CLI 不在で bootstrap 全体を止めると、他ターゲットの配布まで巻き添えになる。
# 失敗は warn に留め、未配備の検知は harness-doctor.sh が別途担う。
install_codex_plugin() {
  local marketplace="$HOME/.codex/harness-marketplace"

  if ! command -v codex >/dev/null 2>&1; then
    skip "codex CLI が無いため harunon-core plugin の配備をスキップ"
    return 0
  fi
  if [[ -n "$DRY_RUN_FLAG" ]]; then
    info "dry-run: would build $marketplace and run 'codex plugin add harunon-core@harunon-local'"
    return 0
  fi

  if ! "$PYTHON_BIN" "$REPO_ROOT/scripts/build-codex-plugin.py" --output "$marketplace" >/dev/null; then
    warn "harunon-core plugin のビルドに失敗しました。Codex 側の guard は更新されていません"
    return 0
  fi
  if ! codex plugin marketplace add "$marketplace" >/dev/null 2>&1; then
    warn "codex plugin marketplace add に失敗しました（${marketplace}）"
    return 0
  fi
  if ! codex plugin add harunon-core@harunon-local >/dev/null 2>&1; then
    warn "codex plugin add harunon-core@harunon-local に失敗しました"
    return 0
  fi
  ok "harunon-core plugin: Codex へ配備しました"
}

# --- Step 1.75: 外部 skill (rulesync) を取得（push のときだけ・fail-closed） ---
# rulesync.lock の locked ref で .rulesync/skills/.curated/ を揃える。中身は
# claude / shared-agents の distribute[skills/].source に含まれており、Step 2 の
# distribute push が他の source と同じ distribution ledger で管理する（--check で
# drift 検出、--push --prune で退役分を削除。ADR-011 Update 2026-08-30。
# 旧 bootstrap Step 2.5 の bash rm -rf コピーは廃止）。
#
# fail-closed にする理由: CLAUDE.md と rules が /tdd・/diagnosing-bugs 等を名指しで参照する。
# 取得失敗を黙って通すと、参照先不在のまま配布完了と報告してしまう。
if [[ "$MODE" == "push" ]] && [[ -f "$REPO_ROOT/rulesync.lock" ]]; then
  banner "Step 1.75: 外部 skill (rulesync install)"
  if [[ -n "$DRY_RUN_FLAG" ]]; then
    info "dry-run: would run 'rulesync install --frozen'"
  else
    RULESYNC_TOKEN=""
    if command -v gh >/dev/null 2>&1; then
      RULESYNC_TOKEN="$(gh auth token 2>/dev/null || true)"
    fi
    if ! GITHUB_TOKEN="$RULESYNC_TOKEN" mise exec -- rulesync install --frozen; then
      echo "ERROR: rulesync install --frozen 失敗。外部 skill を配布できません" >&2
      echo "  ネットワーク / gh auth を確認するか、rulesync.jsonc と rulesync.lock のズレを直してください" >&2
      exit 1
    fi
    ok "rulesync install --frozen"
  fi
fi

if [[ "$MODE" == "push" ]]; then
  case " $TARGETS " in
    *" codex "*)
      banner "Step 1.9: codex plugin (harunon-core)"
      install_codex_plugin
      ;;
  esac
fi

# --- Step 2: 各ターゲットを MODE で実行 ---
overall_rc=0
for target in $TARGETS; do
  banner "$MODE $target"

  DEST_FLAG=()
  case "$MODE" in
    push)
      if [[ "$target" == "claude" ]] && [[ -n "${CLAUDE_DIR:-}" ]]; then
        DEST_FLAG=(--dest "$CLAUDE_DIR")
        info "CLAUDE_DIR override: $CLAUDE_DIR"
      fi
      ;;
    check|pull)
      if [[ "$target" == "claude" ]] && [[ -n "${CLAUDE_DIR:-}" ]]; then
        DEST_FLAG=(--live "$CLAUDE_DIR")
        info "CLAUDE_DIR override: $CLAUDE_DIR"
      fi
      ;;
  esac

  set +e
  "$PYTHON_BIN" "$REPO_ROOT/scripts/distribute.py" "$target" "--$MODE" \
      ${DEST_FLAG[@]+"${DEST_FLAG[@]}"} \
      --repo-root "$REPO_ROOT" \
      ${DRY_RUN_FLAG:+"$DRY_RUN_FLAG"}
  rc=$?
  set -e

  if [[ "$MODE" == "check" ]]; then
    # check の exit code: 0 = drift なし、1 = drift あり（結果）、それ以外 = 内部/設定エラー。
    # drift とエラーを区別せず `✓` を出すと、config 破損や submodule 不在を「確認済み」
    # と誤読する（2026-08-29 Codex 監査 P1）。
    case "$rc" in
      0) ok "check $target" ;;
      1)
        warn "check $target: drift あり"
        overall_rc=1
        ;;
      *)
        echo "ERROR: check $target failed (exit $rc)" >&2
        overall_rc=$rc
        ;;
    esac
    continue
  elif [[ "$rc" -ne 0 ]]; then
    echo "ERROR: $MODE $target failed" >&2
    exit 1
  fi
  ok "$MODE $target"
done

# --- Step 3: .githooks を有効化 ---
# 未設定なら自動で .githooks に設定する。既に別の値が設定済みの場合は上書きせず警告のみ。
if [[ "$MODE" == "push" ]] && [[ -d "$REPO_ROOT/.githooks" ]]; then
  current="$(git -C "$REPO_ROOT" config --get core.hooksPath 2>/dev/null || echo "")"
  if [[ -z "$current" ]]; then
    if [[ -n "$DRY_RUN_FLAG" ]]; then
      info "dry-run: would set core.hooksPath .githooks"
    else
      git -C "$REPO_ROOT" config core.hooksPath .githooks
      ok "core.hooksPath を .githooks に設定"
    fi
  elif [[ "$current" != ".githooks" ]]; then
    warn "core.hooksPath は既に '$current' に設定されています。.githooks へは上書きしません（手動で 'git config core.hooksPath .githooks' を実行してください）"
  fi
fi

banner "完了"
exit $overall_rc

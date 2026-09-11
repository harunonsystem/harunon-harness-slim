#!/usr/bin/env bash
# harness-doctor.sh — harness 健康診断の統合エントリポイント
#
# 実行内容:
#   0. 前提ツールチェック    — required ツール欠如で exit 1、recommended 欠如は WARN
#        0.6. global mise env — mise.global.example.toml の [env] と live のドリフトを警告のみ
#        0.7. ツール更新      — 宣言済みツールに新版が出ていれば警告のみ（上げる判断は人）
#   0.5. 未管理スキル        — ~/.claude/skills / ~/.agents/skills に宣言の無い skill で exit 1
#   1. validate-harness.py  — SSOT メタ整合チェック（error で exit 1）
#   2. bootstrap.sh --check   — 各ターゲットの live ↔ SSOT ドリフト確認（drift で exit 1）
#
# 実行例:
#   ./scripts/harness-doctor.sh                          # 全チェック
#   ./scripts/harness-doctor.sh --meta-only              # メタ整合のみ（前提ツールは常に実行）
#   ./scripts/harness-doctor.sh --drift-only              # ドリフトのみ（前提ツールは常に実行）
#   ./scripts/harness-doctor.sh --skip-prereq             # 前提ツールチェックをスキップ
#   ./scripts/harness-doctor.sh --targets claude          # 特定ターゲットのドリフトのみ
#   ./scripts/harness-doctor.sh --json                    # validate-harness を JSON 出力
#
# 環境変数:
#   CLAUDE_DIR         claude target の live ディレクトリ override（bootstrap.sh と同じ）
#   AGENTS_SKILLS_DIR  ~/.agents/skills の override（未管理スキル判定）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Tests and callers may provide an explicit interpreter. Otherwise resolve the
# project-managed Python from mise.toml; never fall back to system python3.
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if ! command -v mise > /dev/null 2>&1; then
    printf 'ERROR: mise が見つかりません。Python は mise 管理の3.14を使用します。\n' >&2
    exit 2
  fi
  PYTHON_BIN="$(cd "$REPO_ROOT" && mise which python3)"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'ERROR: mise 管理のPython 3.14が見つかりません: %s\n' "$PYTHON_BIN" >&2
  exit 2
fi
RUN_META=true
RUN_DRIFT=true
RUN_PREREQ=true
JSON_FLAG=""
TARGETS_VALUE=""

usage() {
  cat <<'USAGE'
Usage: ./scripts/harness-doctor.sh [--meta-only|--drift-only] [--skip-prereq] [--targets LIST] [--json]

Run harness health checks:
  0. 前提ツールチェック（required/recommended）
  0.5. 未管理スキル（常に実行）
  1. validate-harness.py
  2. bootstrap.sh --check

Options:
  --meta-only       Run only validate-harness.py
  --drift-only      Run only bootstrap.sh --check
  --skip-prereq     Skip the prerequisite tool check
  --targets LIST    Forward target list to bootstrap.sh --check
  --json            Forward --json to validate-harness.py
  -h, --help        Show this help
USAGE
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

# --- args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --meta-only)
      RUN_DRIFT=false
      shift
      ;;
    --drift-only)
      RUN_META=false
      shift
      ;;
    --skip-prereq)
      RUN_PREREQ=false
      shift
      ;;
    --json)
      JSON_FLAG="--json"
      shift
      ;;
    --targets)
      [[ $# -ge 2 ]] || die "--targets requires a value"
      [[ -n "$2" ]] || die "--targets requires a value"
      TARGETS_VALUE="$2"
      shift 2
      ;;
    --targets=*)
      target_value="${1#--targets=}"
      [[ -n "$target_value" ]] || die "--targets requires a value"
      TARGETS_VALUE="$target_value"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

# --- helpers ---
banner(){ printf '\n━━━ %s ━━━\n' "$1"; }
ok()    { printf '  ✓ %s\n' "$1"; }
fail()  { printf '  ✗ %s\n' "$1"; }
warn()  { printf '  ⚠ %s\n' "$1"; }

overall_rc=0

# --- Step 0: 前提ツール ---
# required: 無いと配布/hook が壊れるツール（欠如で FAIL）
# recommended: 無くても動くが運用が劣化するツール（欠如で WARN + 導入ヒント）
if $RUN_PREREQ; then
  banner "Step 0: 前提ツール"

  check_required() {
    local tool="$1"
    if command -v "$tool" > /dev/null 2>&1; then
      ok "$tool"
    else
      fail "$tool が見つかりません（必須）"
      overall_rc=1
    fi
  }

  check_recommended() {
    local tool="$1"
    local hint="$2"
    if command -v "$tool" > /dev/null 2>&1; then
      ok "$tool"
    else
      warn "$tool が見つかりません（推奨）: $hint"
    fi
  }

  for req_tool in git jq perl shasum; do
    check_required "$req_tool"
  done
  ok "mise Python 3.14: $PYTHON_BIN"

  check_recommended rtk        "packages/core/RTK.md 参照（Rust Token Killer 導入手順）"
  check_recommended gwm        "cargo install gwm（worktree 管理。導入なしでも手動 worktree 運用は可能）"
  check_recommended shellcheck "brew install shellcheck（shell script 検証）"
  check_recommended node       "mise install node（各種 CLI ツールの前提ランタイム）"
  check_recommended codex      "npm i -g @openai/codex（Codex CLI）"
  check_recommended opencode   "npm i -g opencode-ai（OpenCode CLI）"
  check_recommended pi         "mise use --global --pin npm:@earendil-works/pi-coding-agent（バージョンは mise config の pin が正。プロジェクトの Node 固定に影響されない pi CLI）"
  check_recommended omp        "npm i -g @oh-my-pi/pi-coding-agent（omp CLI）"

  env_file="$REPO_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    if grep -qE '^BLOCKED_TERMS=' "$env_file"; then
      ok ".env: BLOCKED_TERMS 定義済み"
    else
      warn ".env はあるが BLOCKED_TERMS 未定義: .env に BLOCKED_TERMS=... を追記してください（pre-commit の禁止語チェックが機能しません）"
    fi
  else
    warn ".env が見つかりません: 'cp .env.example .env' で作成し BLOCKED_TERMS を設定してください（./scripts/bootstrap.sh の対話生成でも可）"
  fi

  hooks_path="$(git -C "$REPO_ROOT" config --get core.hooksPath 2>/dev/null || echo "")"
  if [[ "$hooks_path" == ".githooks" ]]; then
    ok "core.hooksPath: .githooks"
  else
    warn "core.hooksPath が .githooks ではありません（現在値: '${hooks_path:-未設定}'）: 'git config core.hooksPath .githooks' を実行してください"
  fi

  # OpenAI Codex auth の存在確認（secrets は harness が肩代わりしない。live API の疎通は行わない）
  codex_auth="$HOME/.codex/auth.json"
  if [[ -s "$codex_auth" ]]; then
    ok "codex auth: credential file present (live availability is not verified)"
  else
    warn "codex auth が見つかりません: Codex で login を実行してください（自動 fallback はしません）"
  fi

  # Codex plugin（harunon-core）の配備確認。bootstrap は plugins/ を配らない
  # （Codex のアプリ管理状態なので packages/targets/codex/config.json で対象外）ため、
  # ここが唯一の検知点になる。CI は「ビルドできること」しか見ないので、未インストールでも
  # 未更新でも緑のままになる（2026-07-12 の追加から 2026-09-05 まで未インストールのまま
  # 誰も気づかず、その間の修正が一度もライブに届いていなかった）。
  # ls をパイプで受けると、glob 不一致の exit 1 を pipefail が拾って set -e で
  # スクリプトごと黙って落ちる（未インストール = まさに検知したいケースで落ちる）。
  # 外部コマンドを使わず glob を直接回す
  # 比較対象は adapter だけでなく、同梱される hook 群と policy も含める。adapter 1 ファイル
  # だけを見ていた間は、hook を足しても policy を変えても「installed and current」と表示され、
  # Codex 側だけ古い guard が動き続けた（2026-09-06 に block-secrets-in-commit を足して発覚）。
  codex_install_hint="'$PYTHON_BIN scripts/build-codex-plugin.py --output ~/.codex/harness-marketplace' → 'codex plugin marketplace add ~/.codex/harness-marketplace' → 'codex plugin add harunon-core@harunon-local'"
  set +e
  codex_plugin_output="$("$PYTHON_BIN" "$REPO_ROOT/scripts/check-codex-plugin.py" 2>&1)"
  codex_plugin_rc=$?
  set -e
  if [[ "$codex_plugin_rc" -eq 0 ]]; then
    ok "$codex_plugin_output"
  else
    printf '%s\n' "$codex_plugin_output" | while IFS= read -r line; do warn "$line"; done
    warn "  入れ直してください: $codex_install_hint"
  fi

  # features.json の実測 default が、いま入っている codex と合っているか。
  # validator（codex-features）は table と config.toml の整合しか見ない（CI に codex CLI が
  # 無いため）ので、宣言が codex の更新で陳腐化したことに気づけるのはここだけ。
  set +e
  codex_features_output="$("$PYTHON_BIN" "$REPO_ROOT/scripts/check-codex-features.py" 2>&1)"
  codex_features_rc=$?
  set -e
  case "$codex_features_rc" in
    0) ok "$codex_features_output" ;;
    1)
      warn "codex features.json が実測とずれています:"
      printf '%s\n' "$codex_features_output" | while IFS= read -r line; do warn "  $line"; done
      ;;
    *)
      # 検査できなかった状態を ✓ にしない（唯一の陳腐化チェックが動いていない）
      warn "$codex_features_output"
      ;;
  esac

  omp_agent_db="$HOME/.omp/agent/agent.db"
  if [[ -s "$omp_agent_db" ]]; then
    ok "omp auth storage: agent.db present (provider/live availability is not verified)"
  else
    warn "omp auth storage が見つかりません: omp を起動して auth/login を実行してください（自動 fallback はしません）"
  fi

  # pi の初回 auth セットアップ（secrets は harness が肩代わりしない。案内のみ）
  pi_auth="$HOME/.pi/agent/auth.json"
  zen_key=""
  if [[ -f "$HOME/.local/share/opencode/auth.json" ]] && command -v jq >/dev/null 2>&1; then
    zen_key="$(jq -r '.opencode.key // empty' "$HOME/.local/share/opencode/auth.json" 2>/dev/null)"
  fi
  if [[ -s "$pi_auth" ]] && jq -e 'has("openai-codex") and .["openai-codex"] != null' "$pi_auth" >/dev/null 2>&1; then
    ok "pi auth: openai-codex credential file present (live availability is not verified)"
  elif [[ -s "$pi_auth" ]] && [[ "$(cat "$pi_auth")" != "{}" ]]; then
    warn "pi auth: credential file has no openai-codex entry; other providers are available only for explicit fallback"
  elif [[ -n "$zen_key" ]]; then
    warn "pi auth: OpenAI Codex credential missing; Zen key is available only for explicit fallback"
  else
    warn "pi 初回セットアップ未了: pi を起動して /login（openai-codex サブスク）。契約終了後の fallback は明示的な --model 指定で行ってください"
  fi

  banner "Step 0.6: global mise env"
  set +e
  "$PYTHON_BIN" "$REPO_ROOT/scripts/mise-global-check.py"
  mise_env_rc=$?
  set -e
  case "$mise_env_rc" in
    0) ok "global mise: 宣言どおり" ;;
    1)
      warn "global mise の [env] が SSOT と一致しません（詳細は下記の出力）: ./scripts/setup-machine.sh を実行してください（env を確認付きで反映）"
      ;;
    *)
      echo "ERROR: global mise env チェックが失敗しました (exit $mise_env_rc)" >&2
      overall_rc=1
      ;;
  esac

  # Step 0 は「入っているか」しか見ないので、pin したまま古い版を使い続けても
  # 気づけない。宣言済みツールに新版が出ていれば warn で出す（上げるかは破壊的
  # 変更の有無を見て人が判断するので fail にはしない）。
  banner "Step 0.7: ツール更新"
  set +e
  tool_updates_output="$("$PYTHON_BIN" "$REPO_ROOT/scripts/check-tool-updates.py" 2>&1)"
  tool_updates_rc=$?
  set -e
  case "$tool_updates_rc" in
    0) ok "$tool_updates_output" ;;
    *)
      # 1 = 新版あり、2 = 検査できなかった。どちらも ✓ にしない（検査が走らなかった
      # 状態を「最新」と読み違えないため）。上げる判断は人に残すので fail にはしない。
      printf '%s\n' "$tool_updates_output" | while IFS= read -r line; do warn "$line"; done
      ;;
  esac
fi

# --- Step 0.5: 未管理スキル ---
# ~/.claude/skills と ~/.agents/skills に core / extras / rulesync.lock / allowlist の
# どこにも宣言が無い skill があれば FAIL。以前は .githooks/pre-push が push を block して
# いたが、push する PR と無関係なローカル環境の状態なので環境診断へ移した（2026-08-29）。
# 判定ロジックは scripts/harness_lib/unmanaged_skills.py（pre-push の警告表示と共有）。
unmanaged_cli="$REPO_ROOT/scripts/harness_lib/unmanaged_skills.py"
if [[ -f "$unmanaged_cli" ]]; then
  banner "Step 0.5: 未管理スキル"
  set +e
  unmanaged_output="$("$PYTHON_BIN" "$unmanaged_cli" \
    --repo-root "$REPO_ROOT" \
    --claude-dir "${CLAUDE_DIR:-$HOME/.claude}" \
    --agents-skills-dir "${AGENTS_SKILLS_DIR:-$HOME/.agents/skills}")"
  unmanaged_rc=$?
  set -e
  unmanaged_list="$(printf '%s\n' "$unmanaged_output" | tail -n +2)"
  if [[ "$unmanaged_rc" -ne 0 ]]; then
    fail "未管理スキルあり（core / extras / rulesync.lock / allowlist のどこにも宣言が無い）"
    printf '%s\n' "$unmanaged_list" | while IFS= read -r s; do
      [[ -n "$s" ]] && printf '      - %s\n' "$s"
    done
    printf '    → rulesync.jsonc に source 追記 / packages/core/skills へ追加 / unmanaged-skills-allowlist.json に宣言 / 削除\n'
    overall_rc=1
  elif [[ -n "$unmanaged_list" ]]; then
    warn "未管理の可能性があるスキルあり（extras submodule 未初期化のため判定不能）"
    printf '%s\n' "$unmanaged_list" | while IFS= read -r s; do
      [[ -n "$s" ]] && printf '      - %s\n' "$s"
    done
  else
    ok "未管理スキルなし"
  fi
fi

# --- Step 1: メタ整合 ---
if $RUN_META; then
  banner "Step 1: meta validation (validate-harness.py)"
  set +e
  if [[ -n "$JSON_FLAG" ]]; then
    "$PYTHON_BIN" "$REPO_ROOT/scripts/validate-harness.py" \
      --repo-root "$REPO_ROOT" \
      "$JSON_FLAG"
  else
    "$PYTHON_BIN" "$REPO_ROOT/scripts/validate-harness.py" \
      --repo-root "$REPO_ROOT"
  fi
  meta_rc=$?
  set -e

  if [[ "$meta_rc" -ne 0 ]]; then
    fail "meta validation failed (exit $meta_rc)"
    overall_rc=1
  else
    ok "meta validation passed"
  fi
fi

# --- Step 2: ドリフト ---
if $RUN_DRIFT; then
  banner "Step 2: distribution drift (bootstrap.sh --check)"
  set +e
  if [[ -n "$TARGETS_VALUE" ]]; then
    bash "$REPO_ROOT/scripts/bootstrap.sh" --check --targets "$TARGETS_VALUE"
  else
    bash "$REPO_ROOT/scripts/bootstrap.sh" --check
  fi
  drift_rc=$?
  set -e

  if [[ "$drift_rc" -ne 0 ]]; then
    fail "drift detected (exit $drift_rc)"
    overall_rc=1
  else
    ok "no drift detected"
  fi
fi

banner "診断完了"
if [[ "$overall_rc" -eq 0 ]]; then
  ok "harness healthy"
else
  fail "issues found — see output above"
fi

exit $overall_rc

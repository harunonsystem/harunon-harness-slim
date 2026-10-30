#!/usr/bin/env bash
# harunon-slim 対話型セットアップ
#
#   scripts/setup.sh [--target TARGET] [--preset PRESET] [--dest DIR] [--dry-run] [-y|--yes]
#
# ユーザーまたは AI エージェントが対話的（またはフラグ指定）に
# 適切なプロファイルを選択して harunon-harness-slim を導入・設定します。
#
# PRESET:
#   recommended      : 推奨フルパック（安全ガードレール + 思考モード medium + 安全コマンド自動許可 + 日本語）
#   guardrails-only  : ガードレールのみ（危険コマンド拒否 + 安全フックのみ。モデル・権限は変更しない）
#   custom           : 対話形式で項目ごとに選択
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_NAME="install-manifest.json"

TARGET=""
PRESET=""
DEST=""
DRY_RUN=0
ASSUME_YES=0

usage() {
  echo "Usage: $0 [--target TARGET] [--preset PRESET] [--dest DIR] [--dry-run] [-y|--yes]"
  echo "  --target TARGET   配布先ターゲット名 (claude, codex, opencode, pi, omp, shared-agents)"
  echo "  --preset PRESET   導入プロファイル: recommended | guardrails-only | custom"
  echo "  --dest DIR        配布先ディレクトリ（省略時はランタイムの既定値）"
  echo "  --dry-run         変更内容のプレビューのみ（ファイル書き込みなし）"
  echo "  -y, --yes         対話確認をスキップし、推奨値（recommended）で自動実行"
}

list_targets() {
  local dir
  for dir in "$REPO_ROOT"/*/; do
    [ -f "$dir/$MANIFEST_NAME" ] && basename "$dir"
  done
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      TARGET="$1"
      ;;
    --preset)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      PRESET="$1"
      ;;
    --dest)
      shift
      [ "$#" -gt 0 ] || { usage >&2; exit 2; }
      DEST="$1"
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    -y|--yes)
      ASSUME_YES=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

command -v jq >/dev/null 2>&1 || { echo "エラー: jq が必要です" >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "エラー: rsync が必要です" >&2; exit 1; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  harunon-harness-slim セットアップ"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- 1. ターゲットの決定 -------------------------------------------------------

if [ -f "$REPO_ROOT/$MANIFEST_NAME" ]; then
  # 単一 payload repo (pi-agent-slim 等)
  TARGET="root"
elif [ -z "$TARGET" ]; then
  if [ "$ASSUME_YES" -eq 1 ]; then
    TARGET="claude"
  else
    echo ""
    echo "導入先の AI ランタイムを選択してください:"
    echo "  1) claude        (Claude Code: ~/.claude) [推奨・デフォルト]"
    echo "  2) codex         (Codex CLI: ~/.codex)"
    echo "  3) opencode      (OpenCode: ~/.config/opencode)"
    echo "  4) pi            (pi coding agent: ~/.pi/agent)"
    echo "  5) omp           (oh-my-pi: ~/.omp/agent)"
    echo "  6) shared-agents (共有スキル: ~/.agents)"
    printf "番号または名前を入力 [1]: "
    read -r target_choice
    case "${target_choice:-1}" in
      1|claude) TARGET="claude" ;;
      2|codex) TARGET="codex" ;;
      3|opencode) TARGET="opencode" ;;
      4|pi) TARGET="pi" ;;
      5|omp) TARGET="omp" ;;
      6|shared-agents) TARGET="shared-agents" ;;
      *)
        echo "エラー: 無効な選択肢です: $target_choice" >&2
        exit 1
        ;;
    esac
  fi
fi

# --- 2. プロファイルの決定 -----------------------------------------------------

if [ -z "$PRESET" ]; then
  if [ "$ASSUME_YES" -eq 1 ]; then
    PRESET="recommended"
  else
    echo ""
    echo "導入プロファイルを選択してください:"
    echo "  1) recommended     [推奨] フルパック"
    echo "                     - 安全ガードレール（危険コマンド拒否 + フック）"
    echo "                     - 思考モードの有効化 (effortLevel: medium)"
    echo "                     - 安全な読み取りコマンドの自動許可 (承認待ちプロンプト防止)"
    echo "                     - 日本語出力設定 (language: Japanese)"
    echo "  2) guardrails-only ガードレールのみ"
    echo "                     - 危険コマンド拒否と安全フックのみ導入"
    echo "                     - モデル設定・思考モード・権限許可は一切変更しない"
    echo "  3) custom          カスタム設定（対話形式で項目ごとに選択）"
    printf "番号または名前を入力 [1]: "
    read -r preset_choice
    case "${preset_choice:-1}" in
      1|recommended) PRESET="recommended" ;;
      2|guardrails-only) PRESET="guardrails-only" ;;
      3|custom) PRESET="custom" ;;
      *)
        echo "エラー: 無効なプロファイルです: $preset_choice" >&2
        exit 1
        ;;
    esac
  fi
fi

# --- 3. カスタム選択（custom の場合） -------------------------------------------

ENABLE_THINKING=0
ENABLE_PERMISSIONS=0
ENABLE_JAPANESE=0

if [ "$PRESET" = "recommended" ]; then
  ENABLE_THINKING=1
  ENABLE_PERMISSIONS=1
  ENABLE_JAPANESE=1
elif [ "$PRESET" = "custom" ]; then
  echo ""
  echo "▼ 詳細設定の選択:"
  printf "  思考モード (Thinking: medium) を有効にしますか？ (熟考させ浅い回答を防ぎます) [Y/n]: "
  read -r ans_thinking
  [[ -z "$ans_thinking" || "$ans_thinking" =~ ^[Yy] ]] && ENABLE_THINKING=1

  printf "  安全な読み取りコマンド (git, cat, ls, grep 等) を自動許可しますか？ [Y/n]: "
  read -r ans_perm
  [[ -z "$ans_perm" || "$ans_perm" =~ ^[Yy] ]] && ENABLE_PERMISSIONS=1

  printf "  言語を日本語 (Japanese) に設定しますか？ [Y/n]: "
  read -r ans_ja
  [[ -z "$ans_ja" || "$ans_ja" =~ ^[Yy] ]] && ENABLE_JAPANESE=1
fi

# --- 4. install.sh の実行 ------------------------------------------------------

echo ""
echo "▼ パッケージの配布中..."

install_args=()
[ "$TARGET" != "root" ] && install_args+=("$TARGET")
[ -n "$DEST" ] && install_args+=(--dest "$DEST")
[ "$DRY_RUN" -eq 1 ] && install_args+=(--dry-run)

"$REPO_ROOT/scripts/install.sh" "${install_args[@]}"

# --- 5. 推奨設定のマージ（設定有効時） ---------------------------------------

resolve_target_dest() {
  local manifest="$1"
  if [ -n "$DEST" ]; then
    printf '%s' "$DEST"
    return 0
  fi
  local config_dir_env config_dir tilde
  config_dir_env="$(jq -r '.configDirEnv // empty' "$manifest")"
  if [ -n "$config_dir_env" ] && [ -n "${!config_dir_env:-}" ]; then
    printf '%s' "${!config_dir_env}"
    return 0
  fi
  config_dir="$(jq -r '.configDir' "$manifest")"
  tilde='~'
  case "$config_dir" in
    "$tilde") printf '%s' "$HOME" ;;
    "$tilde/"*) printf '%s' "$HOME/${config_dir#*/}" ;;
    *) printf '%s' "$config_dir" ;;
  esac
}

backup_and_replace() {
  local target_file="$1"
  local new_content_file="$2"
  local dest_dir="$3"
  local backup_timestamp
  backup_timestamp="$(date +%Y%m%d%H%M%S)"
  local base_name
  base_name="$(basename "$target_file")"
  local backup_file="$dest_dir/.harunon-slim.backups/$backup_timestamp/${base_name}.preset-before"
  mkdir -p "$(dirname "$backup_file")"
  cp -pP "$target_file" "$backup_file"
  chmod 600 "$new_content_file"
  mv "$new_content_file" "$target_file"
  echo "  ✓ 推奨設定をマージしました: $target_file (バックアップ: $backup_file)"
}

if [ "$PRESET" != "guardrails-only" ] && [ "$TARGET" != "shared-agents" ]; then
  target_manifest="$REPO_ROOT/$TARGET/$MANIFEST_NAME"
  if [ -f "$target_manifest" ]; then
    actual_dest="$(resolve_target_dest "$target_manifest")"

    if [ "$TARGET" = "claude" ]; then
      target_settings="$actual_dest/settings.json"
      preset_file="$REPO_ROOT/presets/claude-recommended.json"
      if [ -f "$target_settings" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo ""
        echo "▼ Claude Code 推奨設定の適用中..."
        tmp_settings="$(mktemp "${TMPDIR:-/tmp}/harness-setup-settings.XXXXXX")"
        if [ "$PRESET" = "recommended" ] && [ -f "$preset_file" ]; then
          jq -s '
            .[0] as $orig | .[1] as $patch |
            ($orig * $patch) |
            if $patch.permissions.allow then
              .permissions.allow = (($orig.permissions.allow // []) + $patch.permissions.allow | unique)
            else
              .
            end
          ' "$target_settings" "$preset_file" > "$tmp_settings"
        else
          # custom 選択項目だけを適用
          patch_obj="{}"
          if [ "$ENABLE_THINKING" -eq 1 ]; then
            patch_obj="$(echo "$patch_obj" | jq '. + {effortLevel: "medium", alwaysThinkingEnabled: true}')"
          fi
          if [ "$ENABLE_JAPANESE" -eq 1 ]; then
            patch_obj="$(echo "$patch_obj" | jq '. + {language: "Japanese"}')"
          fi
          if [ "$ENABLE_PERMISSIONS" -eq 1 ] && [ -f "$preset_file" ]; then
            allowed_list="$(jq '.permissions.allow // []' "$preset_file")"
            patch_obj="$(echo "$patch_obj" | jq --argjson allow "$allowed_list" '. + {permissions: {allow: $allow}}')"
          fi
          jq -s '
            .[0] as $orig | .[1] as $patch |
            ($orig * $patch) |
            if $patch.permissions.allow then
              .permissions.allow = (($orig.permissions.allow // []) + $patch.permissions.allow | unique)
            else
              .
            end
          ' "$target_settings" <(echo "$patch_obj") > "$tmp_settings"
        fi
        backup_and_replace "$target_settings" "$tmp_settings" "$actual_dest"
      fi

    elif [ "$TARGET" = "codex" ]; then
      target_config="$actual_dest/config.toml"
      preset_file="$REPO_ROOT/presets/codex-recommended.toml"
      if [ -f "$target_config" ] && [ -f "$preset_file" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo ""
        echo "▼ Codex 推奨設定の適用中..."
        tmp_config="$(mktemp "${TMPDIR:-/tmp}/harness-setup-config.XXXXXX")"
        cp "$target_config" "$tmp_config"
        while IFS= read -r line || [ -n "$line" ]; do
          [ -z "$line" ] && continue
          key="$(echo "$line" | cut -d'=' -f1 | tr -d ' ')"
          if ! grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$tmp_config"; then
            echo "$line" >> "$tmp_config"
          fi
        done < "$preset_file"
        backup_and_replace "$target_config" "$tmp_config" "$actual_dest"
      fi

    elif [ "$TARGET" = "opencode" ]; then
      target_json="$actual_dest/opencode.json"
      preset_file="$REPO_ROOT/presets/opencode-recommended.json"
      if [ -f "$target_json" ] && [ -f "$preset_file" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo ""
        echo "▼ OpenCode 推奨設定の適用中..."
        tmp_json="$(mktemp "${TMPDIR:-/tmp}/harness-setup-json.XXXXXX")"
        jq -s '.[0] * .[1]' "$target_json" "$preset_file" > "$tmp_json"
        backup_and_replace "$target_json" "$tmp_json" "$actual_dest"
      fi

    elif [ "$TARGET" = "pi" ]; then
      target_json="$actual_dest/settings.json"
      preset_file="$REPO_ROOT/presets/pi-recommended.json"
      if [ -f "$target_json" ] && [ -f "$preset_file" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo ""
        echo "▼ pi agent 推奨設定の適用中..."
        tmp_json="$(mktemp "${TMPDIR:-/tmp}/harness-setup-json.XXXXXX")"
        jq -s '.[0] * .[1]' "$target_json" "$preset_file" > "$tmp_json"
        backup_and_replace "$target_json" "$tmp_json" "$actual_dest"
      fi

    elif [ "$TARGET" = "omp" ]; then
      target_yml="$actual_dest/config.yml"
      preset_file="$REPO_ROOT/presets/omp-recommended.yml"
      if [ -f "$target_yml" ] && [ -f "$preset_file" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo ""
        echo "▼ oh-my-pi 推奨設定の適用中..."
        tmp_yml="$(mktemp "${TMPDIR:-/tmp}/harness-setup-yml.XXXXXX")"
        python3 -c "
import yaml
with open('$target_yml') as f:
    orig = yaml.safe_load(f) or {}
with open('$preset_file') as f:
    patch = yaml.safe_load(f) or {}
for k, v in patch.items():
    if isinstance(v, dict) and isinstance(orig.get(k), dict):
        orig[k].update(v)
    else:
        orig[k] = v
with open('$tmp_yml', 'w') as f:
    yaml.dump(orig, f, default_flow_style=False, allow_unicode=True)
" 2>/dev/null || cat "$target_yml" "$preset_file" > "$tmp_yml"
        backup_and_replace "$target_yml" "$tmp_yml" "$actual_dest"
      fi
    fi
  fi
fi

# Codex / OpenCode / pi / omp を導入した場合、shared-agents の配布も自動案内・実行
if [[ "$TARGET" =~ ^(codex|opencode|pi|omp)$ ]] && [ -d "$REPO_ROOT/shared-agents" ]; then
  shared_dest="$(resolve_target_dest "$REPO_ROOT/shared-agents/$MANIFEST_NAME")"
  if [ ! -d "$shared_dest/skills" ] && [ "$DRY_RUN" -eq 0 ]; then
    echo ""
    echo "▼ 共通スキル (shared-agents: ~/.agents) を配布中..."
    "$REPO_ROOT/scripts/install.sh" shared-agents
  fi
fi

# --- 6. 完了報告と鉄則案内 -----------------------------------------------------

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎉 harunon-harness-slim のセットアップが完了しました！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 AIに「アホ！！」と叫ばないための3つの鉄則:"
echo "  1. 最初は「コードはまだ書かないで。設計と質問だけ出して」と言う"
echo "     （仕様が決まる前にコードを書かせるとキメラコードになります）"
echo "  2. 実装させたら「テスト/ビルドを実行して、エラーが出たら自分で直して」と添える"
echo "     （AI自身にフィードバックループを回させると劇的に品質が上がります）"
echo "  3. チャットが長くなったら新規チャットにする"
echo "     （ログが溜まるとコンテキストが溢れて急激に物忘れします）"
echo ""
echo "状態の確認: ./scripts/doctor.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

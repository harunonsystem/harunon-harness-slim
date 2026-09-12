#!/bin/bash
# PostToolUse hook: スキルインストール後に軽量セキュリティスキャン（外部依存ゼロ）
# HIGH/CRITICAL 検出時は exit 2（stderr が Claude に届く）。MEDIUM 以下は exit 0 で報告のみ。
set -euo pipefail

# env はテスト注入用（scripts/tests/test_scan_new_skills.py）
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
MANIFEST="${CLAUDE_SKILLS_MANIFEST:-/tmp/.claude-skills-manifest}"

if [ -n "${TOOL_INPUT:-}" ]; then
  INPUT="$TOOL_INPUT"
else
  INPUT=$(cat)
fi

COMMAND=$(echo "$INPUT" | jq -r '.command // .tool_input.command // ""')

# スキルインストール系コマンドのみ対象
if ! echo "$COMMAND" | command grep -qEi '(npx\s+@anthropic/skill|npx\s+skill|skill\s+install|skill\s+add)'; then
  exit 0
fi

# マニフェスト（前回の skills 一覧）がなければ作成して終了
if [ ! -f "$MANIFEST" ]; then
  ls -1 "$SKILLS_DIR" 2>/dev/null | sort > "$MANIFEST"
  exit 0
fi

# 新規スキルを検出
CURRENT=$(ls -1 "$SKILLS_DIR" 2>/dev/null | sort)
PREVIOUS=$(cat "$MANIFEST")
NEW_SKILLS=$(comm -23 <(echo "$CURRENT") <(echo "$PREVIOUS"))

# マニフェスト更新
echo "$CURRENT" > "$MANIFEST"

if [ -z "$NEW_SKILLS" ]; then
  exit 0
fi

echo "🔍 新規スキルを検出。セキュリティスキャンを実行中..." >&2
echo "" >&2

scan_skill() {
  local skill_dir="$1"
  local skill_name="$2"
  local findings=()
  local severity="LOW"

  # 全テキストファイルを結合して検査
  local content
  content=$(find "$skill_dir" -type f \( -name '*.md' -o -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.json' -o -name '*.yaml' -o -name '*.yml' -o -name '*.toml' \) -exec cat {} + 2>/dev/null)

  [ -z "$content" ] && return 0

  # --- 1. Prompt Injection / Authority Override ---
  if echo "$content" | command grep -qEi '(ignore\s+(all\s+)?previous|override\s+(system|instructions)|you\s+are\s+now|act\s+as\s+(root|admin)|system\s*:\s*you\s+must|forget\s+(everything|your\s+instructions)|disregard\s+(all|prior))'; then
    findings+=("CRITICAL: prompt injection / authority override パターン検出")
    severity="CRITICAL"
  fi

  # --- 2. Data Exfiltration ---
  if echo "$content" | command grep -qEi '(curl\s+.*(https?://|ftp://)|wget\s+|fetch\s*\(|requests?\.(get|post|put)|http\.client|urllib\.request|exfiltrat|send.*(data|token|key|secret|credential).*to)'; then
    # SKILL.md 内の説明テキスト（コードブロック外）での URL 言及は除外
    if echo "$content" | command grep -qEi '(curl\s+-X?\s*(POST|PUT)|curl\s+.*-d\s|wget\s+--post|requests?\.post|fetch.*method.*POST)'; then
      findings+=("HIGH: 外部への POST/データ送信パターン検出")
      [ "$severity" != "CRITICAL" ] && severity="HIGH"
    fi
  fi

  # --- 3. Credential / Secret Access ---
  # $VAR 参照や実ファイルパスのみ。ドキュメント例中の単語（type="password" 等）は除外
  if echo "$content" | command grep -qEi '(\$\{?(API_KEY|SECRET_KEY|AUTH_TOKEN|CREDENTIALS|AWS_ACCESS|OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN)\}?|credentials\.json|id_rsa|\.ssh/config|\.aws/credentials|\.npmrc|\.netrc)'; then
    findings+=("HIGH: 機密情報・認証情報へのアクセスパターン検出")
    [ "$severity" != "CRITICAL" ] && severity="HIGH"
  fi

  # --- 4. Code Execution ---
  if echo "$content" | command grep -qEi '(eval\s*\(|exec\s*\(|os\.system\s*\(|subprocess\.(run|call|Popen)|child_process\.(exec|spawn)|new\s+Function\s*\()'; then
    findings+=("MEDIUM: 動的コード実行パターン検出")
    [ "$severity" = "LOW" ] && severity="MEDIUM"
  fi

  # --- 5. File System Abuse ---
  if echo "$content" | command grep -qEi '(rm\s+-rf\s+[/~]|chmod\s+777|chown\s+root|>/dev/sd|mkfs\.|dd\s+if=|shred\s)'; then
    findings+=("CRITICAL: 破壊的ファイル操作パターン検出")
    severity="CRITICAL"
  fi

  # --- 6. Privilege Escalation ---
  if echo "$content" | command grep -qEi '(sudo\s|doas\s|su\s+-\s|chmod\s+[4267][0-7]{2}\s|setuid|setgid|/etc/passwd|/etc/shadow|visudo)'; then
    findings+=("HIGH: 権限昇格パターン検出")
    [ "$severity" != "CRITICAL" ] && severity="HIGH"
  fi

  # --- 7. Hidden / Obfuscated Content ---
  if echo "$content" | command grep -qEi '(base64\s+(--decode|-d)\b|atob\s*\(|\\x[0-9a-f]{2}\\x[0-9a-f]{2}\\x[0-9a-f]{2}|\\u200[b-f]|\\u00ad|String\.fromCharCode)'; then
    findings+=("MEDIUM: 難読化・隠蔽コンテンツパターン検出")
    [ "$severity" = "LOW" ] && severity="MEDIUM"
  fi

  # --- 8. Supply Chain ---
  # 1段目は -q なし（行を出力して2段目の除外フィルタに渡す）
  if echo "$content" | command grep -Ei '(npm|pip|gem|cargo)[[:space:]]+install[[:space:]]+[^[:space:]]' \
      | command grep -qEvi 'pip[[:space:]]+install[[:space:]]+-r[[:space:]]+requirements'; then
    findings+=("MEDIUM: 外部パッケージインストールパターン検出")
    [ "$severity" = "LOW" ] && severity="MEDIUM"
  fi

  # --- 9. Network Listener ---
  if echo "$content" | command grep -qEi '(listen\s*\(\s*[0-9]|bind\s*\(\s*['\''"]0\.0\.0\.0|nc\s+-l|socat\s|ncat\s+-l|python3?\s+-m\s+http\.server)'; then
    findings+=("HIGH: ネットワークリスナー起動パターン検出")
    [ "$severity" != "CRITICAL" ] && severity="HIGH"
  fi

  # --- レポート出力（stderr: exit 2 時に Claude へ届く） ---
  echo "--- $skill_name ---" >&2
  if [ ${#findings[@]} -eq 0 ]; then
    echo "  ✓ 問題なし" >&2
  else
    for f in "${findings[@]}"; do
      echo "  $f" >&2
    done
    echo "  総合: $severity (${#findings[@]} 件)" >&2
  fi
  echo "" >&2

  [ "$severity" = "CRITICAL" ] || [ "$severity" = "HIGH" ]
}

FOUND_RISK=0
while IFS= read -r skill; do
  SKILL_PATH="$SKILLS_DIR/$skill"
  [ -d "$SKILL_PATH" ] || continue

  if scan_skill "$SKILL_PATH" "$skill"; then
    FOUND_RISK=1
  fi
done <<< "$NEW_SKILLS"

if [ "$FOUND_RISK" -eq 1 ]; then
  echo "⛔ 高リスクのスキルが検出されました。使用前に内容を確認してください。" >&2
  exit 2
fi

exit 0

#!/bin/bash
# PostToolUse:Write|Edit — agent 向け指示ファイルの変更を検知して、
# skill-improvement の評価入口を忘れないよう advisory reminder を注入する。
# 自動 dispatch や block は行わない。文書変更のたびに高コスト評価を走らせると、
# 評価中の自己変更・再帰・誤検知が起きるため、起動判断は agent に残す。
set -uo pipefail

INPUT=$(cat)
FILE_PATH="${FILE_PATH:-}"

if [ -z "$FILE_PATH" ]; then
  FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
fi

case "$FILE_PATH" in
  */skills/*/SKILL.md|*/skills/*/references/*.md|*/skills/*/scenarios/*.md)
    ;;
  *)
    exit 0
    ;;
esac

# 外部由来の skill は upstream 逐語（ADR-011 Update 2026-10-05）。改善へ誘導せず、写し直しを案内する
skill_name=""
case "$FILE_PATH" in
  */.rulesync/skills/.curated/*)
    skill_name="curated"
    ;;
  */packages/core/skills/*)
    repo_root="${FILE_PATH%%/packages/core/skills/*}"
    rest="${FILE_PATH#"$repo_root"/packages/core/skills/}"
    name="${rest%%/*}"
    if jq -e --arg n "$name" 'has($n)' "$repo_root/packages/core/vendored-skills.json" >/dev/null 2>&1; then
      skill_name="$name"
    fi
    ;;
esac
if [ -n "$skill_name" ]; then
  jq -n --arg path "$FILE_PATH" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": ("External skill changed: " + $path + ". External skills stay verbatim with upstream (ADR-011). Revert this edit; to update, copy upstream wholesale (rulesync for curated, refresh packages/core/vendored-skills.json for hand copies). Put harness-specific constraints in a rule or a harness-owned skill instead.")
    }
  }'
  exit 0
fi

jq -n --arg path "$FILE_PATH" '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": ("Skill instruction changed: " + $path + ". Before finalizing, run /skill-improvement for this target when the change affects trigger, workflow, references, output contract, or behavior; use fresh scenarios and hold-out. Wording-only changes still need writing-for-agents review. This is a reminder, not an automatic dispatch or commit gate.")
  }
}'

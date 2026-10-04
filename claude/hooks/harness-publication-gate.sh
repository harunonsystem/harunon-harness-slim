#!/usr/bin/env bash
# Shared publication gate. Runtime orchestration and review execution stay native.
set -euo pipefail
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)
if ! CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty'); then
  echo 'Invalid publication hook input' >&2
  exit 2
fi
if ! ACTION=$(printf '%s' "$CMD" | node --input-type=module --eval '
  import { readFileSync } from "node:fs";
  import { pathToFileURL } from "node:url";
  const { classifyPrCommand } = await import(pathToFileURL(process.argv[1]));
  console.log(classifyPrCommand(readFileSync(0, "utf8")) ?? "");
' "$HOOK_DIR/../policy/pr-action.js"); then
  echo 'Publication classifier unavailable' >&2
  exit 2
fi
[[ -z "$ACTION" ]] && exit 0
if [[ "$ACTION" == "pr.ambiguous" ]]; then
  echo 'Ambiguous publication command' >&2
  exit 2
fi
REPO=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
REPO="${REPO:-$PWD}"
REQUEST=$(jq -n --arg repo "$REPO" --arg action "$ACTION" --arg command "$CMD" \
  '{repo:$repo,action:$action,command:$command}')
if ! RESULT=$(printf '%s' "$REQUEST" | python3 "$HOOK_DIR/../policy/harnessctl.py" authorize 2>&1); then
  printf 'Publication blocked: %s\n' "$RESULT" >&2
  exit 2
fi

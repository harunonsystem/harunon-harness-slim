#!/usr/bin/env bash
# payload の静的検証。書き込みはしない。repo 直下または <target>/ 直下の install-manifest.json
# を payload として列挙し、それぞれについて:
#   - install-manifest.json の managedPaths が実在する
#   - 全 JSON が parse できる
#   - shell script（*.sh と bash shebang の実行ファイル）が bash -n / shellcheck を通る
#   - JS / MJS が node --check を通る
#   - Python が compile できる
#   - credential らしき文字列が無い
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "node is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

payloads=()
while IFS= read -r manifest; do
  payloads+=("$(dirname "$manifest")")
done < <(find . -maxdepth 2 -name install-manifest.json -type f | sort)
[ "${#payloads[@]}" -gt 0 ] || { echo "no install-manifest.json found under $REPO_ROOT" >&2; exit 1; }

for payload in "${payloads[@]}"; do
  while IFS= read -r path; do
    [ -e "$payload/$path" ] || { echo "managed path missing: $payload/$path" >&2; exit 1; }
  done < <(jq -r '.managedPaths[]' "$payload/install-manifest.json")
done

json_ok=0
while IFS= read -r file; do
  jq -e . "$file" >/dev/null || { echo "invalid JSON: $file" >&2; exit 1; }
  json_ok=$((json_ok + 1))
done < <(find . -path ./node_modules -prune -o -path ./.git -prune -o -name '*.json' -type f -print | sort)

# bash の shebang を持つ拡張子なしの実行ファイル（launcher 等）も shell として検査する
is_bash_script() {
  local first
  IFS= read -r first < "$1" || return 1
  case "$first" in
    '#!/usr/bin/env bash'|'#!/bin/bash') return 0 ;;
    *) return 1 ;;
  esac
}

shell_files=()
while IFS= read -r file; do
  case "$file" in
    *.sh) ;;
    *) is_bash_script "$file" || continue ;;
  esac
  shell_files+=("$file")
  bash -n "$file"
done < <(find . -path ./.git -prune -o -path ./node_modules -prune -o -type f \( -name '*.sh' -o -perm -u+x \) -print | sort)

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S warning "${shell_files[@]}"
else
  echo "shellcheck not installed; bash -n completed"
fi

while IFS= read -r file; do
  node --check "$file"
done < <(find . -path ./.git -prune -o -path ./node_modules -prune -o -type f \( -name '*.js' -o -name '*.mjs' \) -print | sort)

find . -path ./.git -prune -o -path ./node_modules -prune -o -name '*.py' -type f -print0 \
  | python3 -c '
import sys
for path in filter(None, sys.stdin.buffer.read().split(b"\0")):
    path = path.decode()
    compile(open(path, encoding="utf-8").read(), path, "exec")
'

if find . -type f -not -path './scripts/validate.sh' -not -path './.git/*' -print0 \
  | xargs -0 perl -ne 'if (/(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})/) { print "$ARGV:$.: credential-like token\n"; $found = 1 } END { exit($found ? 0 : 1) }'; then
  echo "credential-like token found" >&2
  exit 1
fi

echo "validated payloads: ${#payloads[@]}, JSON files: $json_ok"
echo "validation passed"

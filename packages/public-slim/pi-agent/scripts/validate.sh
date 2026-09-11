#!/usr/bin/env bash
# harunon-pi-agent-slim の静的検証。書き込みはしない。
#   - 全 JSON が parse できる
#   - shell script が bash -n / shellcheck を通る
#   - extensions の JS / MJS が node --check を通る
#   - policy の Python が compile できる
#   - install-manifest.json の managedPaths が実在する
#   - credential らしき文字列が無い
set -euo pipefail

REPO_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "node is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

json_ok=0
while IFS= read -r file; do
  jq -e . "$file" >/dev/null || { echo "invalid JSON: $file" >&2; exit 1; }
  json_ok=$((json_ok + 1))
done < <(find . -path ./node_modules -prune -o -name '*.json' -type f -print | sort)

shell_files=()
while IFS= read -r file; do
  shell_files+=("$file")
  bash -n "$file"
done < <(find claude-hooks scripts -name '*.sh' -type f | sort)

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S warning "${shell_files[@]}"
else
  echo "shellcheck not installed; bash -n completed"
fi

while IFS= read -r file; do
  node --check "$file"
done < <(find extensions hook-runner \( -name '*.js' -o -name '*.mjs' \) -type f | sort)

python3 - <<'EOF'
from pathlib import Path
for path in sorted(Path("policy").glob("*.py")):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
EOF

while IFS= read -r path; do
  [ -e "$path" ] || { echo "managed path missing: $path" >&2; exit 1; }
done < <(jq -r '.managedPaths[]' install-manifest.json)

if find . -type f -not -path './scripts/validate.sh' -not -path './.git/*' -print0 \
  | xargs -0 perl -ne 'if (/(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})/) { print "$ARGV:$.: credential-like token\n"; $found = 1 } END { exit($found ? 0 : 1) }'; then
  echo "credential-like token found" >&2
  exit 1
fi

echo "validated JSON files: $json_ok"
echo "harunon-pi-agent-slim validation passed"

#!/usr/bin/env bash
# Shared publication gate. Runtime orchestration and review execution stay native.
# 分類（classifyPrCommand）と kernel の authorize 呼び出しは policy/publication-gate.js が持つ。
set -euo pipefail
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
set +e
node --input-type=module --eval '
  import { pathToFileURL } from "node:url";
  const { runAsHook } = await import(pathToFileURL(process.argv[1]));
  process.exitCode = await runAsHook();
' "$HOOK_DIR/../policy/publication-gate.js"
rc=$?
set -e
[[ "$rc" -eq 0 ]] && exit 0
# node 不在・module 欠落も公開操作を素通しさせない（required hook の exit 1 は Claude で非 blocking）
[[ "$rc" -eq 2 ]] || echo "Publication gate unavailable (exit $rc)" >&2
exit 2

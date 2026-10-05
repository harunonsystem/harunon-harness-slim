#!/bin/bash
# UserPromptSubmit — プロンプトとして届いた ! の明示実行（先頭空白可）を補完する（native ! と同じユーザー shell 経路）。
# agent Bash の PreToolUse guard を通る経路ではない。複数行の貼り付けは実行しない。
# timeout は最大25秒、出力は1MiB、背景子孫は処理終了時に止める。
set -uo pipefail
HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec python3 "$HOOK_DIR/lib/run_bang_command.py"

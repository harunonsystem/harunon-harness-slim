#!/usr/bin/env python3
"""global mise（`~/.config/mise/config.toml`）が `mise.global.example.toml` の
`[env]`/`[tools]` 宣言どおりかを確認する（実装は harness_lib.mise_global）。

Usage:
    mise-global-check.py [--example PATH] [--config PATH] [--apply-env] [--yes]

--apply-env を付けない限り読み取り専用。詳細は harness_lib/mise_global.py の docstring
を参照。
"""
from __future__ import annotations

import sys
from pathlib import Path

# setup-machine.sh は新マシンで PATH 上の python3（macOS 標準は 3.9）を掴み得る。
# tomllib は 3.11+ なので、ImportError の traceback ではなく rc 2 + 導入ヒントで止める
if sys.version_info < (3, 11):
    sys.stderr.write(
        f"ERROR: python3 {sys.version.split()[0]} は tomllib 非対応です（3.11+ が必要）。"
        "`mise install` 後に再実行してください\n"
    )
    sys.exit(2)

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from harness_lib.mise_global import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

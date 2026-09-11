#!/usr/bin/env python3
"""mise.toml の `[tools]` に固定したバージョンを 1 つ標準出力に出す。

CI は `npm install -g rulesync@<version>` のようにバージョン文字列を直接必要とする。
これを workflow 側へ literal で写経すると mise.toml との二重管理になり、引き上げたとき
片方だけ動いて静かにズレる。pin の SSOT は mise.toml なので、そこから読む。

CLI:
    python3 scripts/pinned-tool-version.py npm:rulesync

exit 0: バージョンを出力
exit 1: tool が [tools] に無い、または mise.toml が読めない
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MISE_TOML = REPO_ROOT / "mise.toml"


def pinned_version(tool: str, mise_toml: Path) -> str:
    """`[tools]` から tool の pin を返す。宣言が無ければ ValueError。"""
    with mise_toml.open("rb") as f:
        tools = tomllib.load(f).get("tools", {})
    if tool not in tools:
        declared = ", ".join(sorted(tools)) or "(なし)"
        raise ValueError(
            f"{mise_toml.name} の [tools] に {tool} の宣言がありません。宣言済み: {declared}"
        )
    return str(tools[tool])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="[tools] のキー（例: npm:rulesync）")
    parser.add_argument("--mise-toml", type=Path, default=MISE_TOML)
    args = parser.parse_args(argv)

    try:
        print(pinned_version(args.tool, args.mise_toml))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""配備済みの Codex plugin（harunon-core）が SSOT と一致しているか確かめる。

bootstrap は plugins/ を配らない（Codex がアプリ管理する領域なので）。組み立て済みを
`codex plugin add` で入れる運用なので、配備漏れ・未更新を検知できるのは doctor だけ。

以前は adapter（codex_hook.py）1 ファイルだけを比較していたため、hook を足しても
policy を変えても「installed and current」と表示された。実際には Codex 側だけ古い
guard が動き続ける（2026-09-06 に block-secrets-in-commit を足して発覚）。

一時ビルドを挟むと mktemp / builder の失敗で doctor ごと落ちる経路が増えるので、
SSOT のファイルと配備物を直接突き合わせる。

exit code:
  0  一致（または plugin 未配備で、その旨を出力）
  1  SSOT と乖離
"""
from __future__ import annotations

import argparse
import filecmp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_lib.hook_pipeline import load, pipeline  # noqa: E402

ADAPTER_REL = "scripts/codex_hook.py"
POLICY_FILES = ("danger-rules.json", "hook-pipeline.json")


def installed_plugin_root(home: Path) -> Path | None:
    """配備済み plugin の root を返す（複数あれば最後の 1 つ）。無ければ None。"""
    found = sorted(home.glob(".codex/plugins/cache/*/harunon-core/*"))
    return found[-1] if found else None


def expected_files(repo_root: Path) -> dict[str, Path]:
    """plugin 相対パス -> SSOT 側の実体。build-codex-plugin.py が同梱するものと同じ集合。

    hook は hook-pipeline.json が唯一の真実（builder もここから引く）ので、
    ここで名前を再ハードコードしない。
    """
    expected = {ADAPTER_REL: repo_root / "packages/runtimes/codex/harunon-core" / ADAPTER_REL}
    for name in pipeline(load(repo_root), "codex"):
        expected[f"hooks/{name}"] = repo_root / "packages/core/hooks" / name
    for name in POLICY_FILES:
        expected[f"policy/{name}"] = repo_root / "packages/core/policy" / name
    return expected


def drifts(plugin_root: Path, expected: dict[str, Path]) -> list[str]:
    """配備物と SSOT のずれを人が読める行にして返す。"""
    found: list[str] = []
    for rel, source in expected.items():
        if not source.is_file():
            found.append(f"{rel}: SSOT 側が見つかりません（{source}）")
            continue
        installed = plugin_root / rel
        if not installed.is_file():
            found.append(f"{rel}: 配備されていません")
        elif not filecmp.cmp(source, installed, shallow=False):
            found.append(f"{rel}: 配備物が SSOT と異なります")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()

    plugin_root = installed_plugin_root(args.home)
    if plugin_root is None:
        print("codex plugin harunon-core が未インストールです")
        return 1

    found = drifts(plugin_root, expected_files(args.repo_root))
    if not found:
        print(f"codex plugin harunon-core: installed and current（{plugin_root.name}）")
        return 0

    print(f"codex plugin harunon-core が SSOT と乖離しています（{plugin_root}）:")
    for line in found:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

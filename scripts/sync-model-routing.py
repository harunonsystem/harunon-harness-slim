#!/usr/bin/env python3
"""model-routing.json（Sol / Luna ルーティング SSOT）から各 runtime の宣言ファイルの
model / effort を再生成する。

ADR-010 の役割別モデル割当は、これまで codex の toml / pi の settings.json と agents
frontmatter / opencode の agents frontmatter / omp の config.yml modelRoles に手書きで
散らばり、test_model_routing.py の文字列一致だけが束ねていた。判断の SSOT は
packages/core/model-routing.json であり、宣言ファイル側は生成物として導出する
（sync-auto-mode-rules.py が danger-rules.json → settings.json autoMode に対して
行っていることと同じ規律）。

Usage:
    sync-model-routing.py           宣言ファイルの該当キーの値だけを書き換える
    sync-model-routing.py --check   drift のみ検出（exit 1 なら不一致、書き込まない）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.runtime import require_supported_python  # noqa: E402

require_supported_python()

from harness_lib import model_routing  # noqa: E402


def _load_valid_table(repo_root: Path) -> dict:
    table = model_routing.load(repo_root)
    errors = model_routing._validate_table(table, repo_root)
    if errors:
        raise SystemExit(f"{model_routing.TABLE_PATH} が不正です:\n  " + "\n  ".join(errors))
    return table


def check(repo_root: Path) -> int:
    drifts = model_routing.drifts(_load_valid_table(repo_root), repo_root)
    if drifts:
        for line in drifts:
            print(line)
        print(f"\n宣言ファイルが {model_routing.TABLE_PATH} と食い違っています。{model_routing.SYNC_SCRIPT} を実行してください。")
        return 1
    print(f"OK: 宣言ファイルは {model_routing.TABLE_PATH} と一致しています")
    return 0


def sync(repo_root: Path) -> int:
    changed = model_routing.apply(_load_valid_table(repo_root), repo_root)
    if not changed:
        print("OK: 変更なし（既に一致しています）")
        return 0
    for path in changed:
        print(f"更新しました: {path.relative_to(repo_root)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="drift 検出のみ（書き込まない）")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="リポジトリルート（デフォルト: スクリプトの親ディレクトリ）",
    )
    args = parser.parse_args()
    if args.check:
        return check(args.repo_root)
    return sync(args.repo_root)


if __name__ == "__main__":
    sys.exit(main())

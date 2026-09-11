#!/usr/bin/env python3
"""配布期待値の解決・ドリフト検出・配布 CLI。

Usage:
    distribute.py <target> --list                        manifest の相対パス一覧
    distribute.py <target> --check [--dir DIR]           drift 表示。差分あり exit 1 / なし exit 0
    distribute.py <target> --push [--dir DIR] [--dry-run] [--prune]   manifest を dest に書き込む
    distribute.py <target> --pull [--dir DIR] [--dry-run]             live の変更を source に還流

target: packages/targets/ 配下のターゲット名（例: codex, opencode, claude）

--dir DIR:   配布先（live）ディレクトリを明示指定（省略時は configDir）。
             --live / --dest は同じ意味の別名（旧 CLI 互換）
--dry-run:   何が起きるか表示のみ（実際の書き込みを行わない）
--prune:     --push 時、管理ディレクトリ配下の manifest 外ファイルを backup して削除
--repo-root: リポジトリルート（省略時: スクリプトの親ディレクトリ）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.runtime import require_supported_python  # noqa: E402

require_supported_python()

from harness_lib.distribution import Distribution  # noqa: E402  # 深いモジュール (006 C1)
from harness_lib.distribution_output import render_inspection, render_result  # noqa: E402


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def run(args: argparse.Namespace) -> int:
    dist = Distribution(args.repo_root)
    if args.list:
        m = dist.manifest(args.target)
        for path in dist.list_paths(args.target):
            print(path)
        for warning in m.warnings:
            _warn(f"WARN: {warning}")
        return 0
    if args.check:
        return render_inspection(dist.inspect(args.target, args.dir))
    if args.push:
        return render_result(*dist.push(args.target, args.dir, dry_run=args.dry_run, prune=args.prune))
    return render_result(*dist.pull(args.target, args.dir, dry_run=args.dry_run))


def main() -> int:
    parser = argparse.ArgumentParser(description="配布期待値の解決・ドリフト検出・配布")
    parser.add_argument("target", help="ターゲット名（例: codex, opencode, claude）")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--list", action="store_true", help="manifest のパス一覧を出力")
    mode_group.add_argument("--check", action="store_true", help="drift 検出のみ（書き込まない）")
    mode_group.add_argument("--push", action="store_true", help="manifest を dest に書き込む")
    mode_group.add_argument("--pull", action="store_true",
                            help="live の変更を harness 側 source に還流（transform は skip）")

    parser.add_argument(
        "--dir", "--live", "--dest",
        dest="dir",
        type=Path,
        default=None,
        help="配布先（live）ディレクトリを明示指定（省略時は configDir）。--live / --dest は別名",
    )
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="--push/--pull: 何が起きるか表示のみ（実際の書き込みを行わない）")
    parser.add_argument("--prune", action="store_true", default=False,
                        help="--push: 管理ディレクトリ配下の manifest 外ファイルを backup して削除")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="リポジトリルート（デフォルト: スクリプトの親ディレクトリ）",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except (FileNotFoundError, ValueError) as error:
        _warn(f"ERROR: {error}")
        return 2
    except Exception as error:  # noqa: BLE001 - bootstrap --check の drift 表示と誤認させない
        if os.environ.get("HARNESS_DEBUG") == "1":
            raise
        _warn(f"ERROR: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

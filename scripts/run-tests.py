#!/usr/bin/env python3
"""scripts/tests/ の unittest をモジュール単位で並列実行する。

`python3 -m unittest discover` は直列で、hook を subprocess で叩くテスト（1 件 ~150ms）が
180 件以上あるため CI の 65% を占めていた。テストはモジュールごとに独立した tempdir を使う
ので、モジュールを worker プロセスに分散して壁時間を CPU 数で割る。stdlib のみ。

使い方:
  python3 scripts/run-tests.py            # 全モジュール、CPU 数で並列
  python3 scripts/run-tests.py -j 2       # worker 数を指定
  python3 scripts/run-tests.py -k danger  # モジュール名の部分一致で絞る
"""
import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "scripts" / "tests"


def discover_units(tests_dir: Path, top_level: Path, pattern: str | None) -> list[str]:
    """`module.Class` の一覧を、`unittest discover` と同じ loader から作る。

    モジュール単位では 22 クラス持つ test_block_dangerous_in_bash が壁時間の下限になるので、
    TestCase クラスまで割って分散する（setUp/tearDown の tempdir はクラス内で閉じている）。
    discover の結果を辿るので load_tests フックで組まれたスイートも見える。クラス名で再指定
    できないテスト（FunctionTestCase 等）が混ざっていたら無言で落とさず fail closed にする。
    """
    import unittest

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                yield from walk(item)
            else:
                yield item

    loader = unittest.TestLoader()
    suite = loader.discover(str(tests_dir), top_level_dir=str(top_level))
    units: dict[str, None] = {}
    for test in walk(suite):
        cls = type(test)
        if isinstance(test, unittest.loader._FailedTest):  # import error はそのまま失敗として実行させる
            units.setdefault(test._testMethodName, None)  # = import に失敗したモジュール名
            continue
        if not isinstance(test, unittest.TestCase) or isinstance(test, unittest.FunctionTestCase):
            raise SystemExit(f"クラス単位で再実行できないテストがあります: {test.id()}")
        units.setdefault(f"{cls.__module__}.{cls.__qualname__}", None)
    result = list(units)
    if pattern:
        result = [u for u in result if pattern in u]
    return result


def run_unit(unit: str) -> tuple[str, int, float, str]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", unit],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return unit, proc.returncode, time.monotonic() - started, proc.stdout + proc.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # テストは bash hook を fork して待つ IO 待ち中心で CPU バウンドではないので CPU 数の 3 倍に
    # oversubscribe する。実測: 12 コア機で -j 2 = 49.5s / -j 6 = 18.9s / -j 12 = 15.5s、
    # GitHub Actions（cpu_count=2）で -j 2 = 76.7s
    parser.add_argument("-j", "--jobs", type=int, default=(os.cpu_count() or 2) * 3)
    parser.add_argument("-k", "--keyword", help="モジュール名の部分一致フィルタ")
    parser.add_argument("-v", "--verbose", action="store_true", help="成功したモジュールの出力も表示")
    # CI は 2 vCPU で CPU 飽和するため（-j を上げても 74s で変わらない）、job を分けて
    # ランナーを複数使う。クラス一覧は discover 順で決定的なので i 番目から n おきに取る
    parser.add_argument("--shard", metavar="I/N", help="クラス一覧を N 分割した I 番目（1 始まり）だけ実行する")
    args = parser.parse_args()

    units = discover_units(TESTS_DIR, REPO_ROOT, args.keyword)
    if args.shard:
        try:
            index, total = (int(x) for x in args.shard.split("/", 1))
        except ValueError:
            parser.error(f"--shard は I/N の形で指定する: {args.shard!r}")
        if not (1 <= index <= total):
            parser.error(f"--shard の I は 1..N の範囲: {args.shard!r}")
        units = units[index - 1::total]
    if not units:
        print("対象テストがありません", file=sys.stderr)
        return 1

    started = time.monotonic()
    failed: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for unit, code, elapsed, output in pool.map(run_unit, units):
            status = "ok" if code == 0 else "FAIL"
            if code != 0 or args.verbose:
                print(f"{status:4} {elapsed:6.1f}s {unit}", flush=True)
            if code != 0:
                failed.append((unit, output))

    for unit, output in failed:
        print(f"\n===== {unit} =====\n{output}", file=sys.stderr)
    print(f"{len(units)} test classes, {len(failed)} failed, {time.monotonic() - started:.1f}s wall (-j {args.jobs})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

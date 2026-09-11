#!/usr/bin/env python3
"""scripts/run-tests.py（クラス単位並列ランナー）のテスト。

CI と pre-push の unittest gate はこのランナー経由なので、ランナー自身が壊れて偽 green に
なる経路（子プロセス失敗の取りこぼし・discover との乖離・load_tests の無視）を独立に押さえる。
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "run-tests.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_tests_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="run-tests-fixture-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        scripts = self.root / "scripts"
        self.tests = scripts / "tests"
        self.tests.mkdir(parents=True)
        (scripts / "__init__.py").write_text("", encoding="utf-8")
        (self.tests / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy(RUNNER, scripts / "run-tests.py")

    def add_module(self, name: str, body: str) -> None:
        (self.tests / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")

    def run_runner(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / "run-tests.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120,
        )


class TestRunnerExitCodes(RunnerFixture):
    def test_all_green_reports_every_class_and_exits_zero(self):
        self.add_module(
            "test_alpha",
            """
            import unittest
            class One(unittest.TestCase):
                def test_ok(self): pass
            class Two(unittest.TestCase):
                def test_ok(self): pass
            """,
        )
        result = self.run_runner("-j", "2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 test classes, 0 failed", result.stdout)

    def test_single_failing_class_makes_gate_red(self):
        self.add_module(
            "test_alpha",
            """
            import unittest
            class Good(unittest.TestCase):
                def test_ok(self): pass
            class Bad(unittest.TestCase):
                def test_boom(self): self.fail("boom")
            """,
        )
        result = self.run_runner("-j", "2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("test_alpha.Bad", result.stdout)
        self.assertIn("boom", result.stderr)  # 子プロセスの出力が失敗時に転記される

    def test_import_error_module_is_reported_not_skipped(self):
        self.add_module("test_broken", "import does_not_exist_anywhere\n")
        result = self.run_runner()
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_broken", result.stdout)

    def test_keyword_filters_units(self):
        self.add_module(
            "test_alpha",
            """
            import unittest
            class Keep(unittest.TestCase):
                def test_ok(self): pass
            class Drop(unittest.TestCase):
                def test_boom(self): self.fail("must be filtered out")
            """,
        )
        result = self.run_runner("-k", "Keep")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 test classes, 0 failed", result.stdout)


class TestRunnerSharding(RunnerFixture):
    def _three_classes(self) -> None:
        self.add_module(
            "test_alpha",
            """
            import unittest
            class A(unittest.TestCase):
                def test_ok(self): pass
            class B(unittest.TestCase):
                def test_ok(self): pass
            class C(unittest.TestCase):
                def test_ok(self): pass
            """,
        )

    def test_shards_partition_classes_without_overlap_or_gap(self):
        self._three_classes()
        first = self.run_runner("--shard", "1/2")
        second = self.run_runner("--shard", "2/2")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("2 test classes, 0 failed", first.stdout)
        self.assertIn("1 test classes, 0 failed", second.stdout)

    def test_failure_in_one_shard_is_not_hidden_by_the_other(self):
        self.add_module(
            "test_alpha",
            """
            import unittest
            class A(unittest.TestCase):
                def test_ok(self): pass
            class B(unittest.TestCase):
                def test_boom(self): self.fail("boom")
            """,
        )
        # discover 順で A が shard 1、B が shard 2
        self.assertEqual(self.run_runner("--shard", "1/2").returncode, 0)
        self.assertEqual(self.run_runner("--shard", "2/2").returncode, 1)

    def test_invalid_shard_spec_is_rejected(self):
        self._three_classes()
        for spec in ("0/2", "3/2", "a/b", "1"):
            with self.subTest(spec=spec):
                result = self.run_runner("--shard", spec)
                self.assertEqual(result.returncode, 2, result.stderr)  # argparse error


class TestRunnerDiscovery(RunnerFixture):
    def test_load_tests_hook_classes_are_included(self):
        self.add_module(
            "test_hooked",
            """
            import unittest
            class Hidden(unittest.TestCase):
                def test_boom(self): self.fail("must be discovered via load_tests")
            def load_tests(loader, tests, pattern):
                return loader.loadTestsFromTestCase(Hidden)
            """,
        )
        result = self.run_runner()
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_hooked.Hidden", result.stdout)

    def test_function_test_case_fails_closed(self):
        self.add_module(
            "test_functional",
            """
            import unittest
            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])
            """,
        )
        result = self.run_runner()
        self.assertEqual(result.returncode, 1)
        self.assertIn("クラス単位で再実行できないテスト", result.stderr)

    def test_unit_list_matches_stdlib_discover_for_real_suite(self):
        runner = _load_runner_module()
        units = runner.discover_units(REPO_ROOT / "scripts" / "tests", REPO_ROOT, None)
        discovered = unittest.TestLoader().discover(str(REPO_ROOT / "scripts" / "tests"), top_level_dir=str(REPO_ROOT))
        counted = 0
        for unit in units:
            module_name, class_name = unit.rsplit(".", 1)
            cls = getattr(sys.modules[module_name], class_name)
            counted += len(unittest.TestLoader().getTestCaseNames(cls))
        self.assertEqual(counted, discovered.countTestCases())


if __name__ == "__main__":
    unittest.main()

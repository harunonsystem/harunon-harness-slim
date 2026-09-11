#!/usr/bin/env python3
"""hook-pipeline.json と各 runtime の実体の一致検証のテスト。

「今日通る」ことではなく「壊れたときに落ちる」ことを確認する。特に codex の
positional index dispatch のように、集合一致だけを見る validator では
見逃されていた並べ替えを検出できるかを見る。
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib import hook_pipeline as hp  # noqa: E402


MIRRORED = (
    "packages/core/policy/hook-pipeline.json",
    "packages/runtimes/codex/harunon-core/scripts/codex_hook.py",
    "scripts/build-codex-plugin.py",
    "packages/targets/pi/config.json",
    "packages/targets/omp/config.json",
    "packages/targets/opencode/config.json",
    "packages/core/settings.json",
    "schemas/target-config.schema.json",
)


def _mirror_repo(destination: Path) -> None:
    """検証に必要なファイルだけを temp repo へ複製する。"""
    for rel in MIRRORED:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)


class TestTableMatchesReality(unittest.TestCase):
    def test_check_is_clean(self):
        self.assertEqual(hp.check(REPO_ROOT), [])

    def test_pipeline_is_ordered_by_order_field(self):
        table = hp.load(REPO_ROOT)
        for runtime in table["runtimes"]:
            files = hp.pipeline(table, runtime)
            self.assertEqual(files, list(dict.fromkeys(files)), "重複がある")
            if runtime == "omp":
                continue  # omp は guard 1 本だけ（rewrite を持たない）
            self.assertIn("rtk-rewrite.sh", files)
            # rewrite は必ず最後
            self.assertEqual(files[-1], "rtk-rewrite.sh", f"{runtime}: rewrite が末尾でない")


class TestDetectsDrift(unittest.TestCase):
    def test_rehardcoded_codex_hook_list_is_detected(self):
        """codex 側で hook 一覧をハードコードに戻すことを禁止する。

        以前は dispatcher / builder が別々に tuple を持ち、選択は positional index
        だったため、並べ替えても集合一致だけを見る validator は気づかなかった。両側を
        table から導出する形に変えたので、一覧が戻ること自体を検出する。
        """
        for rel in (
            "packages/runtimes/codex/harunon-core/scripts/codex_hook.py",
            "scripts/build-codex-plugin.py",
        ):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _mirror_repo(root)
                path = root / rel
                path.write_text(
                    path.read_text(encoding="utf-8")
                    + '\nCODEX_HOOKS = (\n    "rtk-rewrite.sh",\n)\n',
                    encoding="utf-8",
                )
                errors = hp.check(root)
                self.assertTrue(
                    any(rel in e.message for e in errors),
                    f"再ハードコードが検出されなかった: {errors}",
                )

    def test_hook_missing_from_opencode_distribute_is_detected(self):
        """opencode は hookRunner が table を実行時に読むので、実体照合は runtime/claude-hooks/ の
        配布宣言だけ。table が配線する hook を config.json から消したら検出する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            path = root / "packages/targets/opencode/config.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["distribute"]["runtime/claude-hooks/block-dangerous-in-bash.sh"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any(
                    "opencode/config.json" in e.message and "block-dangerous-in-bash.sh" in e.message
                    for e in errors
                ),
                f"opencode distribute からの hook 欠落が検出されなかった: {errors}",
            )

    def test_rehardcoded_js_hook_list_is_detected(self):
        """hookRunner / adapter に `const HOOKS = [...]` が戻ったら検出する。

        2026-09-03 以前は opencode の bridge が HOOKS 配列を持ち、validator が JS ソースを
        正規表現で逆パースして table と突き合わせていた。table が実行の source になった今、
        一覧がコードに戻ること自体を禁止する（codex の CODEX_HOOKS と同じ規律）。
        """
        for rel in (
            "packages/core/hook-runner/hook-runner.js",
            "packages/core/opencode-plugins/claude-hooks-bridge.js",
            "packages/core/pi-extensions/claude-hooks-bridge.ts",
            "packages/core/omp-extensions/omp-denial-reason.js",
        ):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _mirror_repo(root)
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    'const HOOKS = ["block-grep-in-bash.sh", "rtk-rewrite.sh"];\n',
                    encoding="utf-8",
                )
                errors = hp.check(root)
                self.assertTrue(
                    any(rel in e.message for e in errors),
                    f"JS 側の再ハードコードが検出されなかった: {errors}",
                )

    def test_real_js_adapters_do_not_hardcode_hook_lists(self):
        for rel in hp._HOOK_RUNNER_JS_DIRS:
            for path in sorted((REPO_ROOT / rel).glob("*.[jt]s")):
                with self.subTest(path=path.relative_to(REPO_ROOT)):
                    self.assertNotIn("const HOOKS", path.read_text(encoding="utf-8"))

    def test_hook_dropped_from_claude_settings_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            path = root / "packages/core/settings.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data["hooks"]["PreToolUse"]:
                entry["hooks"] = [
                    h for h in entry.get("hooks", [])
                    if "block-dangerous-in-bash.sh" not in h.get("command", "")
                ]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any("settings.json" in e.message for e in errors),
                f"claude からの hook 欠落が検出されなかった: {errors}",
            )


    def test_malformed_pi_config_is_a_finding_not_an_exception(self):
        """pi/config.json が壊れていても validate 全体を abort させず finding で返す。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            (root / "packages/targets/pi/config.json").write_text("{oops", encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any("packages/targets/pi/config.json" in e.message for e in errors),
                f"壊れた pi config が finding にならなかった: {errors}",
            )

    def test_hook_missing_from_pi_distribute_is_detected(self):
        """table が pi に配線する hook を pi/config.json の distribute から消したら検出する。

        pi は hookRunner が table を実行時に読む（旧 hooks.json は 2026-09-03 に退役）ので、
        配布経路（distribute エントリ）が唯一の実体照合になる。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            path = root / "packages/targets/pi/config.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["distribute"]["claude-hooks/block-dangerous-in-bash.sh"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any(
                    "config.json" in e.message and "block-dangerous-in-bash.sh" in e.message
                    for e in errors
                ),
                f"pi distribute からの hook 欠落が検出されなかった: {errors}",
            )

    def test_extra_pi_distribute_entry_without_table_wiring_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            path = root / "packages/targets/pi/config.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["distribute"]["claude-hooks/verify-before-commit.sh"] = {
                "source": "packages/core/hooks/verify-before-commit.sh"
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any(
                    "config.json" in e.message and "verify-before-commit.sh" in e.message
                    for e in errors
                ),
                f"table に無い distribute エントリが検出されなかった: {errors}",
            )


    def test_hook_missing_from_omp_distribute_is_detected(self):
        """omp は hook 一覧を持たず extension が単一 hook をパスで呼ぶので、
        config.json の claude-hooks/ 配布宣言が omp 側の唯一の実体照合になる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root)
            path = root / "packages/targets/omp/config.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["distribute"]["claude-hooks/block-dangerous-in-bash.sh"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

            errors = hp.check(root)
            self.assertTrue(
                any(
                    "omp/config.json" in e.message and "block-dangerous-in-bash.sh" in e.message
                    for e in errors
                ),
                f"omp distribute からの hook 欠落が検出されなかった: {errors}",
            )

    def test_omp_is_wired_only_to_block_dangerous(self):
        """omp の guard は bash.patterns が主体で、omp-denial-reason.js は deny 理由の説明に
        限定する（決定 2026-08-30）。table の omp 配線を増やすなら absent の理由も見直す。"""
        table = hp.load(REPO_ROOT)
        self.assertEqual(hp.pipeline(table, "omp"), ["block-dangerous-in-bash.sh"])


class TestTableInvariants(unittest.TestCase):
    def _table(self, **overrides) -> dict:
        table = {
            "stages": ["guard", "rewrite"],
            "runtimes": {"a": {"executionModel": "sequential"}},
            "hooks": [
                {
                    "id": "g", "file": "g.sh", "event": "PreToolUse",
                    "stage": "guard", "order": 10,
                    "when": {"tools": ["Bash"]}, "runtimes": ["a"],
                },
                {
                    "id": "r", "file": "r.sh", "event": "PreToolUse",
                    "stage": "rewrite", "order": 20,
                    "when": {"tools": ["Bash"]}, "runtimes": ["a"],
                },
            ],
        }
        table.update(overrides)
        return table

    def test_guard_must_precede_rewrite_in_sequential_runtime(self):
        table = self._table()
        self.assertEqual(hp._check_stage_order(table), [])
        # rewrite を guard より前に置く
        table["hooks"][0]["order"] = 30
        self.assertTrue(hp._check_stage_order(table), "stage 順序違反が検出されなかった")

    def test_parallel_runtime_is_exempt_from_stage_order(self):
        table = self._table(runtimes={"a": {"executionModel": "parallel"}})
        table["hooks"][0]["order"] = 30
        self.assertEqual(hp._check_stage_order(table), [])

    def test_runtime_must_be_declared_or_absent(self):
        table = self._table(runtimes={"a": {"executionModel": "sequential"},
                                      "b": {"executionModel": "sequential"}})
        errors = hp._validate_table(table, REPO_ROOT)
        self.assertTrue(any("absent" in e for e in errors), errors)

    def test_absent_requires_a_reason(self):
        table = self._table()
        table["runtimes"]["b"] = {"executionModel": "sequential"}
        table["hooks"][0]["absent"] = {"b": "   "}
        table["hooks"][1]["absent"] = {"b": "理由あり"}
        errors = hp._validate_table(table, REPO_ROOT)
        self.assertTrue(any("理由が空" in e for e in errors), errors)

    def test_duplicate_order_is_rejected(self):
        table = self._table()
        table["hooks"][1]["order"] = 10
        errors = hp._validate_table(table, REPO_ROOT)
        self.assertTrue(any("重複" in e for e in errors), errors)

    def test_required_must_be_boolean(self):
        table = self._table()
        table["hooks"][0]["required"] = "yes"
        errors = hp._validate_table(table, REPO_ROOT)
        self.assertTrue(any("required" in e and "真偽値" in e for e in errors), errors)

    def test_required_boolean_is_accepted(self):
        table = self._table()
        table["hooks"][0]["required"] = True
        errors = hp._validate_table(table, REPO_ROOT)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

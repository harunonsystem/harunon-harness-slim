"""features.json の実測突き合わせ（陳腐化検知）のずれ判定。"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_codex_features", REPO_ROOT / "scripts" / "check-codex-features.py"
)
check_codex_features = importlib.util.module_from_spec(_spec)
sys.modules["check_codex_features"] = check_codex_features
_spec.loader.exec_module(check_codex_features)

drifts = check_codex_features.drifts


def table(**features) -> dict:
    return {"measuredWith": "codex-cli 0.153.4", "features": features}


DECLARED = {"stage": "stable", "default": False, "shape": "bool", "declare": True, "why": "on"}
RETIRED = {"stage": "removed", "default": False, "shape": "bool", "declare": False, "why": "removed"}


class TestDrifts(unittest.TestCase):
    def test_matching_declaration_is_quiet(self):
        self.assertEqual([], drifts(table(memories=DECLARED), {"memories": ("stable", False)}))

    def test_changed_default_is_reported(self):
        found = drifts(table(memories=DECLARED), {"memories": ("stable", True)})
        self.assertEqual(1, len(found))
        self.assertIn("default が宣言 False → 実測 True", found[0])
        # declare true のフラグが default true になったら宣言する意味が消える。
        self.assertIn("宣言する意味が無くなった", found[0])

    def test_changed_stage_is_reported(self):
        found = drifts(table(memories=DECLARED), {"memories": ("removed", False)})
        self.assertEqual(1, len(found))
        self.assertIn("stage が宣言 stable → 実測 removed", found[0])

    def test_declared_flag_that_vanished_is_reported(self):
        found = drifts(table(memories=DECLARED), {"other": ("stable", True)})
        self.assertEqual(1, len(found))
        self.assertIn("いまの codex に存在しません", found[0])

    def test_absent_declaration_that_came_back_is_reported(self):
        absent = {"stage": "absent", "declare": False, "why": "gone"}
        found = drifts(table(voice_transcription=absent), {"voice_transcription": ("stable", True)})
        self.assertEqual(1, len(found))
        self.assertIn("宣言は absent ですが", found[0])

    def test_absent_declaration_still_gone_is_quiet(self):
        absent = {"stage": "absent", "declare": False, "why": "gone"}
        self.assertEqual([], drifts(table(voice_transcription=absent), {"other": ("stable", True)}))

    def test_undeclared_codex_features_are_not_drift(self):
        """codex は 120 以上 feature を持つ。宣言していないものは「意見が無い」であってずれではない。"""
        measured = {f"flag_{i}": ("stable", True) for i in range(50)}
        measured["memories"] = ("stable", False)
        self.assertEqual([], drifts(table(memories=DECLARED), measured))

    def test_retired_flag_drift_is_reported_too(self):
        """declare false でも、stage が変われば判断の前提が変わる。"""
        found = drifts(table(js_repl=RETIRED), {"js_repl": ("stable", False)})
        self.assertEqual(1, len(found))
        self.assertIn("stage が宣言 removed → 実測 stable", found[0])


class TestShippedTable(unittest.TestCase):
    def test_parsing_a_features_list_line(self):
        """stage は "under development" のように空白を含む。両端から取る。"""
        parsed = {}
        for line in (
            "context_management                       under development  false",
            "memories                                 stable             false",
        ):
            parts = line.split()
            parsed[parts[0]] = (" ".join(parts[1:-1]), parts[-1] == "true")
        self.assertEqual(("under development", False), parsed["context_management"])
        self.assertEqual(("stable", False), parsed["memories"])


if __name__ == "__main__":
    unittest.main()

"""computedFeatures: feature table からの keys/removeKeys 導出と、table ↔ config.toml の整合検証。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_lib.settings_sync import _computed_feature_keys  # noqa: E402
from harness_lib.validators.codex_features import check_codex_features  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

BOOL_ON = {"stage": "stable", "default": False, "shape": "bool", "declare": True, "why": "on"}
BOOL_OFF = {"stage": "stable", "default": True, "shape": "bool", "declare": False, "why": "既定と同値"}
TABLE_ON = {
    "stage": "stable",
    "default": False,
    "shape": "table",
    "fields": ["enabled", "tool_namespace"],
    "declare": True,
    "why": "既定値に戻したくない",
}


class TestComputedFeatureKeys(unittest.TestCase):
    """declare フラグが keys / removeKeys のどちらに落ちるか。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _cfg(self, features: dict) -> dict:
        (self.repo / "features.json").write_text(
            json.dumps({"measuredWith": "x", "measuredAt": "2026-09-06", "features": features}),
            encoding="utf-8",
        )
        return {
            "settingsSync": {
                "computedFeatures": {"table": "features.json", "prefix": "features"},
            }
        }

    def test_declare_true_becomes_a_key_and_false_becomes_a_removal(self):
        cfg = self._cfg({"memories": BOOL_ON, "hooks": BOOL_OFF})
        declared, retired = _computed_feature_keys(cfg, self.repo)
        self.assertEqual(("features.memories",), declared)
        self.assertEqual(("features.hooks",), retired)

    def test_absent_declaration_derives_nothing(self):
        self.assertEqual(((), ()), _computed_feature_keys({"settingsSync": {}}, self.repo))
        self.assertEqual(((), ()), _computed_feature_keys({}, self.repo))

    def test_table_outside_the_repo_is_rejected(self):
        cfg = {
            "settingsSync": {
                "computedFeatures": {"table": "../escape.json", "prefix": "features"},
            }
        }
        with self.assertRaises(ValueError):
            _computed_feature_keys(cfg, self.repo)


class TestCodexFeaturesValidator(unittest.TestCase):
    """feature table と config.toml がずれたら error にする。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "packages/targets/codex").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, features: dict, config_toml: str):
        base = self.repo / "packages/targets/codex"
        (base / "features.json").write_text(
            json.dumps({"measuredWith": "x", "measuredAt": "2026-09-06", "features": features}),
            encoding="utf-8",
        )
        (base / "config.toml").write_text(config_toml, encoding="utf-8")
        (base / "config.json").write_text(
            json.dumps({
                "name": "codex",
                "settingsSync": {
                    "source": "packages/targets/codex/config.toml",
                    "keys": [],
                    "format": "toml",
                    "computedFeatures": {
                        "table": "packages/targets/codex/features.json",
                        "prefix": "features",
                    },
                },
            }),
            encoding="utf-8",
        )

    def _messages(self) -> list[str]:
        return [f.message for f in check_codex_features(self.repo)]

    def test_matching_table_and_config_is_clean(self):
        self._write(
            {"memories": BOOL_ON, "hooks": BOOL_OFF},
            "[features]\nmemories = true\n",
        )
        self.assertEqual([], self._messages())

    def test_declared_flag_missing_from_config_is_reported(self):
        self._write({"memories": BOOL_ON}, "[features]\n")
        self.assertIn("declare true", "\n".join(self._messages()))

    def test_table_shaped_flag_written_as_bool_is_reported(self):
        """bool で書くと codex 既定に戻る。今回の実害そのもの。"""
        self._write(
            {"multi_agent_v2": TABLE_ON},
            "[features]\nmulti_agent_v2 = true\n",
        )
        self.assertIn("bool で書かれています", "\n".join(self._messages()))

    def test_table_fields_out_of_sync_is_reported(self):
        self._write(
            {"multi_agent_v2": TABLE_ON},
            '[features.multi_agent_v2]\nenabled = true\n',
        )
        self.assertIn("fields が table と不一致", "\n".join(self._messages()))

    def test_retired_flag_still_written_is_reported(self):
        self._write(
            {"hooks": BOOL_OFF},
            "[features]\nhooks = true\n",
        )
        self.assertIn("declare false", "\n".join(self._messages()))

    def test_flag_written_but_absent_from_table_is_reported(self):
        """table に無いフラグは declare の判断も撤去宣言も漏れる。"""
        self._write({}, "[features]\nsome_new_flag = true\n")
        self.assertIn("table にありません", "\n".join(self._messages()))


class TestShippedCodexFeatureTable(unittest.TestCase):
    """配布中の feature table そのものの内容を固定する。"""

    def test_declared_features_match_the_measured_table(self):
        table = json.loads(
            (REPO_ROOT / "packages/targets/codex/features.json").read_text(encoding="utf-8")
        )
        declared = {name for name, e in table["features"].items() if e["declare"]}
        self.assertEqual({"memories", "context_management", "multi_agent_v2"}, declared)
        # 実測 default が off のものだけを明示的に有効化している。
        for name in declared:
            self.assertFalse(table["features"][name]["default"], msg=name)

    def test_the_shipped_config_passes_its_own_validator(self):
        self.assertEqual([], check_codex_features(REPO_ROOT))


if __name__ == "__main__":
    unittest.main()

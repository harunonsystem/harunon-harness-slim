#!/usr/bin/env python3
"""settingsSync.computedGlobs（danger-rules.json 由来の計算 overlay）のテスト。

opencode/omp の permission map は checked-in ファイルに直書きせず、danger-rules.json
から distribute 時に計算して template にマージする。ここでは settings_sync.compose
を通してそのマージ結果を検証する（実ファイルの生成結果そのものは
test_danger_rules.py の golden テストが担保）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness_lib import settings_sync  # noqa: E402


_TABLE_REL = "packages/core/policy/danger-rules.json"


def _rule(rule_id: str, target: str, globs: list, action: str = "block", override: str | None = None) -> dict:
    rule = {
        "id": rule_id, "action": action, "impl": "table",
        "targets": [target],
        "match": {"globs": {target: globs}},
    }
    if override:
        rule["overrides"] = {target: {"action": override, "reason": "test"}}
    return rule


class _ComputedGlobsFixture(unittest.TestCase):
    """template（json）+ danger-rules table + computedGlobs 宣言を持つ最小 repo。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.live = self.root / "live"
        (self.repo / "packages" / "core" / "policy").mkdir(parents=True)
        self.live.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_table(self, rules: list) -> None:
        (self.repo / _TABLE_REL).write_text(
            json.dumps({
                "version": 1,
                "constants": {
                    "originEre": "x", "chainOnlyOriginEre": "x",
                    "wordEndEre": "x", "originJs": "x",
                },
                "rules": rules,
            }),
            encoding="utf-8",
        )

    def compose(self, template: dict, live: dict | None, keys: list, computed: dict | None):
        (self.repo / "template.json").write_text(json.dumps(template), encoding="utf-8")
        if live is not None:
            (self.live / "config.json").write_text(json.dumps(live), encoding="utf-8")
        spec = {"source": "template.json", "keys": keys, "format": "json"}
        if computed is not None:
            spec["computedGlobs"] = {"table": _TABLE_REL, **computed}
        cfg = {"configFile": "config.json", "settingsSync": spec}
        return settings_sync.compose(cfg, self.repo, self.live)

    def composed_data(self, *args) -> dict:
        return json.loads(self.compose(*args).text)


_FLAT = {"target": "opencode", "mergeKey": "permission.bash", "mergeShape": "flat"}
_ORDERED = {"target": "omp", "mergeKey": "bash.patterns", "mergeShape": "orderedPatterns"}


class ComputedGlobsFlatShapeTestCase(_ComputedGlobsFixture):
    """mergeShape="flat"（opencode の permission.bash 形式）。"""

    def test_is_noop_when_computed_globs_spec_is_absent(self):
        self.write_table([_rule("git-push", "opencode", ["git push *"])])
        template = {"permission": {"bash": {"ls *": "allow"}}}
        data = self.composed_data(template, {"permission": {"bash": {"ls *": "allow"}}}, ["permission"], None)
        self.assertEqual(data, template)

    def test_adds_table_derived_globs_to_existing_flat_map(self):
        self.write_table([
            _rule("git-push", "opencode", ["git push *"], override="confirm"),
            _rule("git-reset-hard", "opencode", ["git reset --hard*"]),
        ])
        data = self.composed_data(
            {"permission": {"bash": {"ls *": "allow", "*": "ask"}}},
            {"permission": {"bash": {"ls *": "allow", "*": "ask"}}},
            ["permission"], _FLAT,
        )
        self.assertEqual(
            data["permission"]["bash"],
            {"ls *": "allow", "*": "ask", "git push *": "ask", "git reset --hard*": "deny"},
        )

    def test_creates_merge_key_when_absent(self):
        self.write_table([_rule("gh-api", "opencode", ["gh api*"], override="confirm")])
        data = self.composed_data({"permission": {}}, {"permission": {}}, ["permission"], _FLAT)
        self.assertEqual(data["permission"]["bash"], {"gh api*": "ask"})

    def test_seeded_template_includes_computed_globs(self):
        """configFile 不在時の seed は生 template ではなく計算 overlay 込みで書かれる。"""
        self.write_table([_rule("git-reset-hard", "opencode", ["git reset --hard*"])])
        composed = self.compose({"permission": {"bash": {}}}, None, ["permission"], _FLAT)
        self.assertTrue(composed.seeded)
        self.assertEqual([step.kind for step in composed.steps], ["settings-template"])
        self.assertEqual(json.loads(composed.text)["permission"]["bash"], {"git reset --hard*": "deny"})


class ComputedGlobsUnknownShapeTestCase(_ComputedGlobsFixture):
    """未知の mergeShape（廃止済みの "tiered" 含む）は fail fast で落とす。"""

    def test_raises_on_removed_tiered_shape(self):
        self.write_table([_rule("git-push", "omp", ["git push *"], override="confirm")])
        with self.assertRaises(ValueError):
            self.compose(
                {"permissions": {"bash": {}}}, {"permissions": {"bash": {}}}, ["permissions"],
                {"target": "omp", "mergeKey": "permissions.bash", "mergeShape": "tiered"},
            )


class ComputedGlobsOrderedPatternsShapeTestCase(_ComputedGlobsFixture):
    """mergeShape="orderedPatterns"（omp の bash.patterns 形式）。"""

    def test_creates_merge_key_when_absent(self):
        self.write_table([_rule("gh-api", "omp", ["gh api*"], override="confirm")])
        data = self.composed_data({}, {}, ["bash.patterns"], _ORDERED)
        self.assertEqual(data["bash"]["patterns"], [{"match": "gh api*", "approval": "prompt"}])

    def test_deny_entries_are_placed_before_prompt_entries(self):
        # table の並びは prompt が先でも、deny を必ず先頭に置く
        # （first-match-wins で broad な prompt が narrower な deny を食う事故を防ぐ）。
        self.write_table([
            _rule("gh-api", "omp", ["gh api*"], override="confirm"),
            _rule("rm-rf", "omp", ["rm -rf*"]),
        ])
        data = self.composed_data({"bash": {"patterns": []}}, {"bash": {"patterns": []}}, ["bash.patterns"], _ORDERED)
        self.assertEqual(
            data["bash"]["patterns"],
            [
                {"match": "rm -rf*", "approval": "deny"},
                {"match": "gh api*", "approval": "prompt"},
            ],
        )

    def test_preexisting_non_computed_entries_are_kept_at_the_end(self):
        self.write_table([_rule("rm-rf", "omp", ["rm -rf*"])])
        template = {"bash": {"patterns": [{"match": "npm test*", "approval": "allow"}]}}
        data = self.composed_data(template, {"bash": {"patterns": []}}, ["bash.patterns"], _ORDERED)
        self.assertEqual(
            data["bash"]["patterns"],
            [
                {"match": "rm -rf*", "approval": "deny"},
                {"match": "npm test*", "approval": "allow"},
            ],
        )

    def test_composing_an_already_composed_live_is_idempotent(self):
        self.write_table([
            _rule("gh-api", "omp", ["gh api*"], override="confirm"),
            _rule("rm-rf", "omp", ["rm -rf*"]),
        ])
        template = {"bash": {"patterns": [{"match": "npm test*", "approval": "allow"}]}}
        first = self.compose(template, {"bash": {"patterns": []}}, ["bash.patterns"], _ORDERED)
        self.assertEqual(len(first.steps), 1)
        second = self.compose(template, json.loads(first.text), ["bash.patterns"], _ORDERED)
        self.assertEqual(second.steps, ())
        self.assertEqual(json.loads(second.text), json.loads(first.text))

    def test_omp_git_globs_expand_to_rtk_variants(self):
        self.write_table([_rule("git-reset-hard", "omp", ["git reset --hard*"])])
        data = self.composed_data({"bash": {"patterns": []}}, {"bash": {"patterns": []}}, ["bash.patterns"], _ORDERED)
        self.assertEqual(
            data["bash"]["patterns"],
            [
                {"match": "git reset --hard*", "approval": "deny"},
                {"match": "rtk git reset --hard*", "approval": "deny"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

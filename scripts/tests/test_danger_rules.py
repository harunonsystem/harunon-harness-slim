#!/usr/bin/env python3
"""danger_rules.py（危険コマンドルール SSOT table の検証）のテスト。"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness_lib import danger_rules  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class SchemaValidationTestCase(unittest.TestCase):
    """table の schema が壊れているとき _validate_schema が違反を検出するか検証する。"""

    def test_returns_empty_when_table_is_well_formed(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{"id": "sample-rule", "action": "block", "impl": "table", "targets": ["claude"]}],
        }
        self.assertEqual(danger_rules._validate_schema(table, _REPO_ROOT), [])

    def test_reports_error_when_action_is_not_in_vocabulary(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{"id": "sample-rule", "action": "deny-forever", "impl": "table"}],
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("action" in e for e in errors))

    def test_reports_error_when_override_is_missing_reason(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{
                "id": "sample-rule", "action": "block", "impl": "table",
                "overrides": {"opencode": {"action": "confirm"}},
            }],
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("reason" in e for e in errors))

    def test_reports_error_when_rule_id_is_duplicated(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [
                {"id": "dup-rule", "action": "block", "impl": "table"},
                {"id": "dup-rule", "action": "warn", "impl": "table"},
            ],
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("重複" in e for e in errors))

    def test_reports_error_when_constants_is_missing_required_key(self):
        table = {
            "version": 1,
            "constants": {"originEre": "x"},
            "rules": [{"id": "sample-rule", "action": "block", "impl": "table"}],
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("constants" in e for e in errors))

    def _table_with_rule(self, rule: dict) -> dict:
        return {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [rule],
        }

    def test_reports_error_when_targets_is_missing(self):
        # schema_validator の必須プロパティ違反メッセージ形式: "missing required property 'targets'"
        table = self._table_with_rule({"id": "sample-rule", "action": "block", "impl": "table"})
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("targets" in e and "missing required property" in e for e in errors), errors)

    def test_reports_error_when_targets_contains_unknown_runtime(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude", "not-a-runtime"],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("targets" in e for e in errors))

    def test_reports_error_when_targets_is_empty(self):
        # targets: [] はどの runtime にも効かない死にルールになるため拒否する
        # （Codex review P2）。schema の minItems: 1 が汎用メッセージ
        # "array length 0 < minItems 1" を返す（死にルール検出という意図は
        # 保たれるが、文言は非空という語彙ではなくなる）。
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": [],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("targets" in e and "minItems" in e for e in errors), errors)

    def test_returns_empty_when_absent_is_well_formed(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "absent": {"omp": "理由"},
        })
        self.assertEqual(danger_rules._validate_schema(table, _REPO_ROOT), [])

    def test_reports_error_when_absent_reason_is_empty(self):
        # schema の pattern: "\S" 違反メッセージ形式: "does not match pattern '\\S'"
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "absent": {"omp": "   "},
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("absent.omp" in e and "pattern" in e for e in errors), errors)

    def test_reports_error_when_absent_targets_unknown_runtime(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "absent": {"not-a-runtime": "理由"},
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("absent" in e for e in errors))

    def test_reports_error_when_absent_overlaps_with_targets(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude", "omp"],
            "absent": {"omp": "理由"},
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("absent" in e and "重複" in e for e in errors))


class SchemaFileTestCase(unittest.TestCase):
    """schemas/danger-rules.schema.json 自体の契約を検証する。"""

    def test_real_repo_table_has_zero_schema_errors(self):
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )
        errors = danger_rules._schema_errors(table, danger_rules._SCHEMA_PATH, "schema", _REPO_ROOT)
        self.assertEqual(errors, [], errors)

    def test_reports_error_for_unknown_top_level_key(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{"id": "sample-rule", "action": "block", "impl": "table", "targets": ["claude"]}],
            "unknownTopLevelKey": "x",
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("unknownTopLevelKey" in e for e in errors), errors)

    def test_reports_error_for_unknown_rule_key(self):
        table = {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{
                "id": "sample-rule", "action": "block", "impl": "table", "targets": ["claude"],
                "unknownRuleKey": "x",
            }],
        }
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("unknownRuleKey" in e for e in errors), errors)


class ExtraTableValidationTestCase(unittest.TestCase):
    """extras table（danger-rules.extra.json）の schema 検証。"""

    def _valid_rule(self, **overrides) -> dict:
        rule = {
            "id": "extras-sample",
            "action": "block",
            "impl": "table",
            "targets": ["claude"],
            "message": "sample",
            "match": {"ere": "sample-cmd", "origin": "none", "wordEnd": True},
        }
        rule.update(overrides)
        return rule

    def test_returns_empty_for_valid_extra_table(self):
        extra = {"version": 1, "rules": [self._valid_rule()]}
        self.assertEqual(danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT), [])

    def test_accepts_top_level_notes(self):
        # extras 実体は table 直下に説明用 notes を持つ。CI は extras submodule 無しで
        # 走るため、ここで合成しないと schema の追従漏れ（DR-EXTRA-NOTES-TEST）を検知できない
        extra = {"version": 1, "notes": "会社固有ルールの説明", "rules": [self._valid_rule()]}
        self.assertEqual(danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT), [])

    def test_reports_error_when_id_collides_with_core(self):
        extra = {"version": 1, "rules": [self._valid_rule(id="git-push")]}
        errors = danger_rules._validate_extra_table(extra, core_ids={"git-push"}, repo_root=_REPO_ROOT)
        self.assertTrue(any("重複" in e for e in errors))

    def test_reports_error_for_custom_impl(self):
        extra = {"version": 1, "rules": [self._valid_rule(impl="custom")]}
        errors = danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any("custom impl" in e for e in errors))

    def test_reports_error_for_globs(self):
        rule = self._valid_rule()
        rule["match"] = {"ere": "sample-cmd", "origin": "none", "globs": {"opencode": ["x*"]}}
        errors = danger_rules._validate_extra_table({"version": 1, "rules": [rule]}, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any("globs" in e for e in errors))

    def test_reports_error_when_ere_is_missing(self):
        rule = self._valid_rule()
        rule["match"] = {"js": "sample-cmd", "origin": "none"}
        errors = danger_rules._validate_extra_table({"version": 1, "rules": [rule]}, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any("match.ere" in e for e in errors))

    def test_reports_error_when_claude_is_not_targeted(self):
        extra = {"version": 1, "rules": [self._valid_rule(targets=["pi"])]}
        errors = danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any("claude" in e for e in errors))

    def test_non_object_table_is_reported_not_crashed(self):
        # トップレベルが配列/null でも AttributeError で落ちず診断を返す（codex review P2）
        for broken in ([], None, "text"):
            with self.subTest(table=broken):
                errors = danger_rules._validate_extra_table(broken, core_ids=set(), repo_root=_REPO_ROOT)
                self.assertTrue(any("オブジェクト" in e for e in errors))

    def test_non_object_rule_entry_is_reported_not_crashed(self):
        extra = {"version": 1, "rules": [None, "text", self._valid_rule()]}
        errors = danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any("オブジェクト" in e for e in errors))


class AutoModeSchemaValidationTestCase(unittest.TestCase):
    """rule.autoMode（claude settings.json への投影元）の schema 検証。"""

    def _table_with_rule(self, rule: dict) -> dict:
        return {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [rule],
        }

    def test_returns_empty_for_well_formed_auto_mode(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "autoMode": [{"tier": "hard_deny", "prose": "危険なので禁止"}],
        })
        self.assertEqual(danger_rules._validate_schema(table, _REPO_ROOT), [])

    def test_reports_error_when_tier_is_not_in_vocabulary(self):
        # schema のパスは "autoMode[0].tier"（"autoMode.tier" という連続文字列ではない）
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "autoMode": [{"tier": "medium_deny", "prose": "x"}],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("autoMode" in e and "tier" in e for e in errors), errors)

    def test_reports_error_when_hard_deny_is_on_non_block_rule(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "confirm", "impl": "table",
            "targets": ["claude"],
            "autoMode": [{"tier": "hard_deny", "prose": "x"}],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("hard_deny" in e and "block" in e for e in errors), errors)

    def test_reports_error_when_soft_deny_is_on_warn_rule(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "warn", "impl": "table",
            "targets": ["claude"],
            "autoMode": [{"tier": "soft_deny", "prose": "x"}],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("soft_deny" in e for e in errors), errors)

    def test_reports_error_when_rule_does_not_target_claude(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["pi"],
            "autoMode": [{"tier": "hard_deny", "prose": "x"}],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("targets に claude" in e for e in errors), errors)

    def test_reports_error_when_prose_is_empty(self):
        table = self._table_with_rule({
            "id": "sample-rule", "action": "block", "impl": "table",
            "targets": ["claude"],
            "autoMode": [{"tier": "hard_deny", "prose": "   "}],
        })
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("prose" in e for e in errors), errors)


class AutoModeRulesTestCase(unittest.TestCase):
    """auto_mode_rules() が $defaults を先頭に、rule 配列順で prose を並べるか検証する。"""

    def test_defaults_come_first_and_prose_follows_rule_order(self):
        table = {"rules": [
            {
                "id": "rule-a", "autoMode": [
                    {"tier": "hard_deny", "prose": "A-hard"},
                    {"tier": "soft_deny", "prose": "A-soft"},
                ],
            },
            {"id": "rule-b", "autoMode": [{"tier": "soft_deny", "prose": "B-soft"}]},
            {"id": "rule-c"},  # autoMode 無し rule は無視される
        ]}
        result = danger_rules.auto_mode_rules(table)
        self.assertEqual(result, {
            "hard_deny": ["$defaults", "A-hard"],
            "soft_deny": ["$defaults", "A-soft", "B-soft"],
        })

    def test_returns_defaults_only_when_no_rule_has_auto_mode(self):
        table = {"rules": [{"id": "rule-a"}]}
        result = danger_rules.auto_mode_rules(table)
        self.assertEqual(result, {"hard_deny": ["$defaults"], "soft_deny": ["$defaults"]})


class AutoModeProjectionCheckTestCase(unittest.TestCase):
    """settings.json の autoMode が danger-rules.json から導出した値と一致するか検証する check。"""

    def _write_settings(self, root: Path, auto_mode: dict | None) -> None:
        core = root / "packages" / "core"
        core.mkdir(parents=True, exist_ok=True)
        data = {"permissions": {}}
        if auto_mode is not None:
            data["autoMode"] = auto_mode
        (core / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    def _table(self) -> dict:
        return {"rules": [
            {"id": "rule-a", "autoMode": [{"tier": "hard_deny", "prose": "H"}]},
            {"id": "rule-b", "autoMode": [{"tier": "soft_deny", "prose": "S"}]},
        ]}

    def test_returns_empty_when_settings_matches_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, {
                "hard_deny": ["$defaults", "H"],
                "soft_deny": ["$defaults", "S"],
            })
            errors = danger_rules._check_auto_mode_projection(self._table(), root)
        self.assertEqual(errors, [])

    def test_reports_error_naming_tier_when_settings_is_missing_auto_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, None)
            errors = danger_rules._check_auto_mode_projection(self._table(), root)
        self.assertTrue(any("hard_deny" in e and "sync-auto-mode-rules.py" in e for e in errors), errors)
        self.assertTrue(any("soft_deny" in e for e in errors), errors)

    def test_reports_error_naming_tier_when_order_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, {
                "hard_deny": ["H", "$defaults"],  # $defaults が先頭でない = 順序違反
                "soft_deny": ["$defaults", "S"],
            })
            errors = danger_rules._check_auto_mode_projection(self._table(), root)
        self.assertTrue(any("hard_deny" in e for e in errors), errors)
        self.assertFalse(any("soft_deny]" in e for e in errors), errors)


class AutoModeSyncKeysCheckTestCase(unittest.TestCase):
    """claude target config.json の settingsSync.keys が autoMode の 2 tier を対で宣言しているか検証する。"""

    def _write_config(self, root: Path, keys: list[str] | None) -> None:
        target_dir = root / "packages" / "targets" / "claude"
        target_dir.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if keys is not None:
            data["settingsSync"] = {"keys": keys}
        (target_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def test_returns_empty_when_both_keys_are_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_config(root, ["autoMode.hard_deny", "autoMode.soft_deny", "hooks"])
            errors = danger_rules._check_auto_mode_sync_keys(root)
        self.assertEqual(errors, [])

    def test_reports_error_when_only_soft_deny_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_config(root, ["autoMode.soft_deny"])
            errors = danger_rules._check_auto_mode_sync_keys(root)
        self.assertTrue(any("欠落: autoMode.hard_deny" in e for e in errors), errors)

    def test_reports_error_when_whole_auto_mode_key_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_config(root, ["autoMode.hard_deny", "autoMode.soft_deny", "autoMode"])
            errors = danger_rules._check_auto_mode_sync_keys(root)
        self.assertTrue(any("廃止" in e for e in errors), errors)

    def test_returns_empty_when_config_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = danger_rules._check_auto_mode_sync_keys(root)
        self.assertEqual(errors, [])


class ClaudeForwardGlobCheckTestCase(unittest.TestCase):
    """rule の match.globs.claude が settings.json の deny に存在しないとき検出するか検証する。"""

    def test_returns_empty_when_glob_exists_in_claude_deny(self):
        rules = [{
            "id": "git-commit", "action": "confirm", "targets": ["claude"],
            "match": {"globs": {"claude": ["Bash(git commit)"]}},
            "overrides": {"claude": {"action": "block", "reason": "ask 層が無いため deny で代替"}},
        }]
        errors = danger_rules._check_claude_forward_globs(rules, claude_deny={"Bash(git commit)"})
        self.assertEqual(errors, [])

    def test_reports_error_when_glob_is_absent_from_claude_deny(self):
        rules = [{
            "id": "git-commit", "action": "block", "targets": ["claude"],
            "match": {"globs": {"claude": ["Bash(git commit)"]}},
        }]
        errors = danger_rules._check_claude_forward_globs(rules, claude_deny=set())
        self.assertTrue(any("Bash(git commit)" in e for e in errors))


class PermissionGlobsGoldenTestCase(unittest.TestCase):
    """permission_globs() が omp の computed bash.patterns surface と完全一致するか検証する。

    packages/targets/omp/config.yml から table 由来の deny/prompt エントリを削除しても、
    distribute 時にこの関数の出力で live の permission map を再構成するため、1件でも
    ずれると生成物が SSOT と食い違う（projection 回帰テスト）。
    """

    OPENCODE_GLOBS = {
        "mise install *pi-coding-agent*": "deny",
        "mise up *pi-coding-agent*": "deny",
        "mise upgrade *pi-coding-agent*": "deny",
        "mise use *pi-coding-agent*": "deny",
        "npm add -g *pi-coding-agent*": "deny",
        "npm i -g *pi-coding-agent*": "deny",
        "npm install -g *pi-coding-agent*": "deny",
        "gh api*": "ask",
        "gh pr close*": "ask",
        "gh pr comment *": "deny",
        "gh pr merge*": "ask",
        "gh release create*": "ask",
        "gh release delete*": "deny",
        "gh repo create*": "deny",
        "gh repo delete*": "deny",
        "gh repo edit*": "deny",
        "gh repo fork*": "deny",
        "gh workflow run*": "ask",
        "git branch -D main*": "deny",
        "git branch -D master*": "deny",
        "git branch -D origin/*": "deny",
        "git checkout --force*": "deny",
        "git checkout -f *": "deny",
        "git clean -fd*": "deny",
        "git clean -fdx*": "deny",
        "git commit *": "ask",
        "git merge main": "deny",
        "git merge main *": "deny",
        "git merge master": "deny",
        "git merge master *": "deny",
        "git merge origin/main*": "deny",
        "git merge origin/master*": "deny",
        "git pull *": "deny",
        "git push": "ask",
        "git push *": "ask",
        "git push --force*": "deny",
        "git push -f": "deny",
        "git push -f *": "deny",
        "git push -u origin main": "deny",
        "git push -u origin main *": "deny",
        "git push -u origin master": "deny",
        "git push origin +*": "deny",
        "git push origin main": "deny",
        "git push origin main *": "deny",
        "git push origin master": "deny",
        "git push origin master *": "deny",
        "git rebase *": "deny",
        "git stash clear*": "deny",
        "git stash drop*": "deny",
        "git remote add*": "deny",
        "git remote prune*": "deny",
        "git remote remove*": "deny",
        "git remote rename*": "deny",
        "git remote rm*": "deny",
        "git remote set-branches*": "deny",
        "git remote set-head*": "deny",
        "git remote set-url*": "deny",
        "git remote update*": "deny",
        "git reset --hard*": "deny",
        "git update-ref *": "deny",
        "netlify deploy*": "deny",
        "netlify build*": "deny",
        "netlify api*": "deny",
        "ntl deploy*": "deny",
        "ntl build*": "deny",
        "ntl api*": "deny",
        "npx netlify-cli*": "deny",
    }

    # omp の実チャネルは bash.patterns。approval 語彙は deny|prompt（2026-08-23
    # 実測: permissions キーは omp が読まない。旧 golden の "ask" は "prompt" に
    # 改名し、git-no-verify の omp glob 4 件を追加した）。
    OMP_GLOBS = {
        "git *commit*--no-verify*": "deny",
        "rtk git *commit*--no-verify*": "deny",
        "git *push*--no-verify*": "deny",
        "rtk git *push*--no-verify*": "deny",
        "git push *": "prompt",
        "rtk git push *": "prompt",
        "git push": "prompt",
        "rtk git push": "prompt",
        "git push origin main": "deny",
        "rtk git push origin main": "deny",
        "git push origin main *": "deny",
        "rtk git push origin main *": "deny",
        "git push origin master": "deny",
        "rtk git push origin master": "deny",
        "git push origin master *": "deny",
        "rtk git push origin master *": "deny",
        "git push --force": "deny",
        "rtk git push --force": "deny",
        "git push --force *": "deny",
        "rtk git push --force *": "deny",
        "git push -f": "deny",
        "rtk git push -f": "deny",
        "git push -f *": "deny",
        "rtk git push -f *": "deny",
        "git push origin +*": "deny",
        "rtk git push origin +*": "deny",
        "git commit *": "prompt",
        "rtk git commit *": "prompt",
        "git commit": "prompt",
        "rtk git commit": "prompt",
        "git branch -D main*": "deny",
        "rtk git branch -D main*": "deny",
        "git branch -D master*": "deny",
        "rtk git branch -D master*": "deny",
        "git update-ref *": "deny",
        "rtk git update-ref *": "deny",
        "git update-ref": "deny",
        "rtk git update-ref": "deny",
        "git clean -fd": "deny",
        "rtk git clean -fd": "deny",
        "git clean -fd *": "deny",
        "rtk git clean -fd *": "deny",
        "git clean -fdx": "deny",
        "rtk git clean -fdx": "deny",
        "git clean -fdx *": "deny",
        "rtk git clean -fdx *": "deny",
        "gh pr merge": "deny",
        "gh pr merge *": "deny",
        "gh pr close": "deny",
        "gh pr close *": "deny",
        "gh repo delete*": "deny",
        "gh repo edit*": "deny",
        "gh repo create*": "deny",
        "gh repo fork*": "deny",
        "gh release delete*": "deny",
        "git merge main": "deny",
        "rtk git merge main": "deny",
        "git merge main *": "deny",
        "rtk git merge main *": "deny",
        "git merge master": "deny",
        "rtk git merge master": "deny",
        "git merge master *": "deny",
        "rtk git merge master *": "deny",
        "git merge origin/main*": "deny",
        "rtk git merge origin/main*": "deny",
        "git merge origin/master*": "deny",
        "rtk git merge origin/master*": "deny",
        "git stash drop": "deny",
        "rtk git stash drop": "deny",
        "git stash drop *": "deny",
        "rtk git stash drop *": "deny",
        "git stash clear": "deny",
        "rtk git stash clear": "deny",
        "git stash clear *": "deny",
        "rtk git stash clear *": "deny",
        "git reset --hard": "deny",
        "rtk git reset --hard": "deny",
        "git reset --hard *": "deny",
        "rtk git reset --hard *": "deny",
        "git checkout -f *": "deny",
        "rtk git checkout -f *": "deny",
        "git checkout -f": "deny",
        "rtk git checkout -f": "deny",
        "git checkout --force*": "deny",
        "rtk git checkout --force*": "deny",
        "npm install -g *pi-coding-agent*": "deny",
        "npm install --global *pi-coding-agent*": "deny",
        "npm i -g *pi-coding-agent*": "deny",
        "npm i --global *pi-coding-agent*": "deny",
        "npm add -g *pi-coding-agent*": "deny",
        "npm add --global *pi-coding-agent*": "deny",
        "mise use *pi-coding-agent*": "deny",
        "mise install *pi-coding-agent*": "deny",
        "mise up *pi-coding-agent*": "deny",
        "mise upgrade *pi-coding-agent*": "deny",
        "netlify deploy": "deny",
        "netlify deploy *": "deny",
        "netlify build": "deny",
        "netlify build *": "deny",
        "netlify api": "deny",
        "netlify api *": "deny",
        "ntl deploy": "deny",
        "ntl deploy *": "deny",
        "ntl build": "deny",
        "ntl build *": "deny",
        "ntl api": "deny",
        "ntl api *": "deny",
        "npx netlify-cli *": "deny",
        "rm -*r*f*": "prompt",
        "rm -*f*r*": "prompt",
        "rm -*R*f*": "prompt",
        "rm -*f*R*": "prompt",
        "sudo rm -*r*f*": "prompt",
        "sudo rm -*f*r*": "prompt",
        "sudo rm -*R*f*": "prompt",
        "sudo rm -*f*R*": "prompt",
        "sudo *": "prompt",
        "*| sh*": "prompt",
        "*|sh*": "prompt",
        "*| bash*": "prompt",
        "*|bash*": "prompt",
        "*| zsh*": "prompt",
        "*|zsh*": "prompt",
        "*| dash*": "prompt",
        "*|dash*": "prompt",
        "dd *of=/dev/*": "prompt",
        "*mkfs*": "prompt",
        "*DROP TABLE*": "prompt",
        "*DROP DATABASE*": "prompt",
        "*drop table*": "prompt",
        "*drop database*": "prompt",
        "*Drop Table*": "prompt",
        "*Drop Database*": "prompt",
    }

    def setUp(self):
        self.table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )

    def test_opencode_globs_match_pinned_checked_in_entries(self):
        self.assertEqual(danger_rules.permission_globs(self.table, "opencode"), self.OPENCODE_GLOBS)

    def test_omp_globs_match_pinned_checked_in_entries(self):
        self.assertEqual(danger_rules.permission_globs(self.table, "omp"), self.OMP_GLOBS)


class OmpProjectionParityTestCase(unittest.TestCase):
    """omp の first-match glob projection が ERE の command variants を保つことを検証する。"""

    def test_omp_projection_adds_rtk_git_and_bare_forms(self):
        table = {
            "rules": [{
                "id": "git-checkout-force",
                "action": "block",
                "targets": ["omp"],
                "match": {
                    "ere": "(git|rtk git)[[:space:]]+checkout[[:space:]]+-f",
                    "globs": {"omp": ["git checkout -f *"]},
                },
            }],
        }
        self.assertEqual(
            danger_rules.permission_globs(table, "omp"),
            {
                "git checkout -f": "deny",
                "git checkout -f *": "deny",
                "rtk git checkout -f": "deny",
                "rtk git checkout -f *": "deny",
            },
        )

    def test_omp_projection_adds_npm_global_alias(self):
        table = {
            "rules": [{
                "id": "agent-cli-unpinned-install",
                "action": "block",
                "targets": ["omp"],
                "match": {
                    "ere": "npm[[:space:]]+(i|install|add)[[:space:]]+(-g|--global)",
                    "globs": {
                        "omp": [
                            "npm install -g *pi-coding-agent*",
                            "npm i -g *pi-coding-agent*",
                            "npm add -g *pi-coding-agent*",
                        ],
                    },
                },
            }],
        }
        projected = danger_rules.permission_globs(table, "omp")
        for command in ("install", "i", "add"):
            self.assertEqual(projected[f"npm {command} --global *pi-coding-agent*"], "deny")

    def test_every_omp_git_glob_has_rtk_twin_and_bare_variant(self):
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )
        projected = danger_rules.permission_globs(table, "omp")
        for glob in projected:
            if not glob.startswith("git "):
                continue
            with self.subTest(glob=glob):
                self.assertIn("rtk " + glob, projected)
                if glob.endswith(" *"):
                    self.assertIn(glob[:-2], projected)

    def test_pi_destructive_rules_have_omp_patterns(self):
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            "rm-recursive-force": (
                "rm -*r*f*", "rm -*f*r*", "rm -*R*f*", "rm -*f*R*",
                "sudo rm -*r*f*", "sudo rm -*f*r*", "sudo rm -*R*f*", "sudo rm -*f*R*",
            ),
            "sudo": ("sudo *",),
            "pipe-to-shell": (
                "*| sh*", "*|sh*", "*| bash*", "*|bash*",
                "*| zsh*", "*|zsh*", "*| dash*", "*|dash*",
            ),
            "dd-device-write": ("dd *of=/dev/*",),
            "mkfs": ("*mkfs*",),
            "sql-drop": (
                "*DROP TABLE*", "*DROP DATABASE*", "*drop table*", "*drop database*",
                "*Drop Table*", "*Drop Database*",
            ),
        }
        rules = {rule["id"]: rule for rule in table["rules"]}
        projected = danger_rules.permission_globs(table, "omp")
        for rule_id, patterns in expected.items():
            with self.subTest(rule=rule_id):
                self.assertIn("omp", rules[rule_id]["targets"])
                for pattern in patterns:
                    self.assertEqual(projected.get(pattern), "prompt")


class NoReintroducedGlobsCheckTestCase(unittest.TestCase):
    """table 由来 glob が checked-in permission map に再混入していないか検証する。"""

    def test_returns_empty_when_checked_in_files_do_not_contain_table_globs(self):
        table = {"rules": [{
            "id": "git-pull", "action": "block", "targets": ["opencode"],
            "match": {"globs": {"opencode": ["git pull *"]}},
        }]}
        with unittest.mock.patch.object(
            danger_rules, "_parse_opencode_bash", return_value=(set(), set())
        ), unittest.mock.patch.object(
            danger_rules, "_parse_omp_bash", return_value=(set(), set())
        ):
            errors = danger_rules._check_no_reintroduced_globs(table, _REPO_ROOT)
        self.assertEqual(errors, [])

    def test_reports_error_when_table_glob_still_present_in_checked_in_file(self):
        table = {"rules": [{
            "id": "git-pull", "action": "block", "targets": ["opencode"],
            "match": {"globs": {"opencode": ["git pull *"]}},
        }]}
        with unittest.mock.patch.object(
            danger_rules, "_parse_opencode_bash", return_value=({"git pull *"}, set())
        ), unittest.mock.patch.object(
            danger_rules, "_parse_omp_bash", return_value=(set(), set())
        ):
            errors = danger_rules._check_no_reintroduced_globs(table, _REPO_ROOT)
        self.assertTrue(any("git pull *" in e for e in errors))


class RuleOrderingTestCase(unittest.TestCase):
    """block-dangerous-in-bash.sh は rules 配列の出現順に custom impl を評価する。

    git-push は承認フラグを消費してから push を許可する。git-no-verify が
    git-push より後にあると、承認済み push に --no-verify を付けたとき
    git-push が先にフラグを消費してから deny され、再承認が必要になってしまう
    （2026-08 レビュー指摘）。git-no-verify は必ず git-push より前で評価される
    順序を保つ。
    """

    def test_git_no_verify_is_evaluated_before_git_push(self):
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )
        ids = [rule["id"] for rule in table["rules"]]
        self.assertLess(
            ids.index("git-no-verify"),
            ids.index("git-push"),
            "git-no-verify は git-push より前に評価されなければならない",
        )


def _effective_rule_ids(table: dict, runtime: str) -> set[str]:
    """block-dangerous-in-bash.sh の jq 選別（targets ∋ runtime、custom または
    match.ere あり、実効 action ≠ confirm）と同じロジックで、runtime が実際に
    hook で評価する rule id 集合を導出する。"""
    ids: set[str] = set()
    for rule in table["rules"]:
        if runtime not in rule.get("targets", []):
            continue
        impl = rule.get("impl", "table")
        if impl == "custom":
            pass
        elif impl == "table" and rule.get("match", {}).get("ere") is not None:
            pass
        else:
            continue
        override = rule.get("overrides", {}).get(runtime)
        effective_action = override["action"] if override else rule["action"]
        if effective_action == "confirm":
            continue
        ids.add(rule["id"])
    return ids


class RuntimeEffectiveRuleSetGoldenTestCase(unittest.TestCase):
    """runtime ごとに block-dangerous-in-bash.sh が実際に選別する rule id 集合を pin する。

    HARNESS_RUNTIME による選別（targets + 実効 action）を導入した際の回帰ガード。
    """

    CLAUDE_CUSTOM = {
        "git-commit-and-push-same-command", "git-push", "git-commit-chain",
        "git-checkout-new-branch-in-main-repo", "gh-api-comment-write",
        "git-no-verify", "codex-companion-sandbox", "gh-pr-merge-close",
    }
    TABLE_ERE = {
        "git-branch-delete-main", "git-update-ref", "git-clean-force",
        "gh-repo-delete-edit", "gh-repo-create",
        "gh-release-delete", "git-rebase", "git-pull", "git-merge-main",
        "git-reset-hard", "git-checkout-force", "git-remote", "gh-pr-comment",
        "rtk-init-global", "xargs-dash-a", "agent-cli-unpinned-install",
        "git-stash-discard", "git-stash", "git-checkout-discard",
        "rm-ssot-source", "netlify-deploy-trigger",
    }
    CLAUDE = CLAUDE_CUSTOM | TABLE_ERE
    PI = CLAUDE - {"codex-companion-sandbox"}
    # git-push / gh-pr-merge-close は opencode override で confirm → hook ではなく
    # native permission の ask（承認 UI）が所有するため hook 経路から外れる。
    OPENCODE = CLAUDE - {"codex-companion-sandbox", "git-push", "gh-pr-merge-close"}
    CODEX = {"git-no-verify", "netlify-deploy-trigger"}

    def setUp(self):
        self.table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )

    def test_claude_effective_rule_set(self):
        self.assertEqual(_effective_rule_ids(self.table, "claude"), self.CLAUDE)

    def test_pi_effective_rule_set(self):
        self.assertEqual(_effective_rule_ids(self.table, "pi"), self.PI)

    def test_opencode_effective_rule_set(self):
        self.assertEqual(_effective_rule_ids(self.table, "opencode"), self.OPENCODE)

    def test_codex_effective_rule_set(self):
        self.assertEqual(_effective_rule_ids(self.table, "codex"), self.CODEX)


class AutoModeSyncKeysProductionPinTestCase(unittest.TestCase):
    """packages/targets/claude/config.json の実宣言が autoMode 2 tier 対を守っているか pin する。"""

    def test_settings_sync_keys_declare_both_tiers_and_not_whole_auto_mode(self):
        config = json.loads(
            (_REPO_ROOT / "packages" / "targets" / "claude" / "config.json").read_text(
                encoding="utf-8"
            )
        )
        keys = config.get("settingsSync", {}).get("keys", [])
        self.assertIn("autoMode.hard_deny", keys)
        self.assertIn("autoMode.soft_deny", keys)
        self.assertNotIn("autoMode", keys)


class EnforcementChannelsCheckTestCase(unittest.TestCase):
    """rule の targets に宣言された各 runtime に enforcement channel が実在するか検証する。

    #100 の再発防止: git-no-verify が targets に omp を持ちながら経路がゼロ
    だった穴を機械検出する check。
    """

    def _write_hook_env(self, root: Path, runtimes: list, hook_text: str) -> None:
        """hook_pipeline.load() と hook 本文読み込みが解決できる最小限の repo レイアウトを作る。"""
        policy_dir = root / "packages" / "core" / "policy"
        hooks_dir = root / "packages" / "core" / "hooks"
        policy_dir.mkdir(parents=True)
        hooks_dir.mkdir(parents=True)
        (policy_dir / "hook-pipeline.json").write_text(
            json.dumps({
                "hooks": [
                    {"id": "block-dangerous-in-bash", "file": "block-dangerous-in-bash.sh", "runtimes": runtimes},
                ],
            }),
            encoding="utf-8",
        )
        (hooks_dir / "block-dangerous-in-bash.sh").write_text(hook_text, encoding="utf-8")

    def test_target_without_any_channel_is_an_error(self):
        # (a) omp の経路は bash.patterns（match.globs.omp）と、omp-denial-reason.js が
        # 呼ぶ hook（match.ere）の 2 つ。どちらも無い table rule は無経路。
        rules = [{
            "id": "fake-omp-no-channel-rule", "action": "block", "impl": "table",
            "targets": ["omp"],
            "match": {"globs": {"opencode": ["fake *"]}},
        }]
        errors = danger_rules._check_enforcement_channels(rules, _REPO_ROOT)
        self.assertTrue(
            any("fake-omp-no-channel-rule" in e and "'omp'" in e for e in errors), errors
        )

    def test_warn_action_with_only_omp_glob_is_an_error(self):
        # Codex review P2: glob が宣言されていても実効 action が warn だと
        # permission_globs() は tier=None でスキップし、bash.patterns に
        # 実際には投影されない。見せかけの経路を経路ありと誤判定しない。
        rules = [{
            "id": "fake-warn-omp-only-rule", "action": "warn", "impl": "table",
            "targets": ["omp"],
            "match": {"globs": {"omp": ["fake-warn-omp-only-rule*"]}},
        }]
        errors = danger_rules._check_enforcement_channels(rules, _REPO_ROOT)
        self.assertTrue(
            any("fake-warn-omp-only-rule" in e and "'omp'" in e for e in errors), errors
        )

    def test_target_outside_hook_pipeline_runtimes_is_an_error(self):
        # (b) hook-pipeline.json の runtimes に居ない runtime を targets に持つ custom rule。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_hook_env(
                root, runtimes=["claude"],
                hook_text="custom_fake_opencode_only_rule() {\n  :\n}\n",
            )
            rules = [{
                "id": "fake-opencode-only-rule", "action": "block", "impl": "custom",
                "targets": ["opencode"],
            }]
            errors = danger_rules._check_enforcement_channels(rules, root)
        self.assertTrue(
            any("fake-opencode-only-rule" in e and "'opencode'" in e for e in errors), errors
        )

    def test_confirm_only_effective_action_without_glob_is_an_error(self):
        # (c) codex は hook 以外に経路を持たない。実効 action が confirm だと
        # hook は対話確認できないため、glob が無ければ無経路になる。
        rules = [{
            "id": "fake-confirm-only-rule", "action": "confirm", "impl": "table",
            "targets": ["codex"],
            "match": {"ere": "fake-confirm-only-rule-pattern"},
        }]
        errors = danger_rules._check_enforcement_channels(rules, _REPO_ROOT)
        self.assertTrue(
            any("fake-confirm-only-rule" in e and "'codex'" in e for e in errors), errors
        )

    def test_orphan_custom_function_is_an_error(self):
        # (d) hook 内の custom_*() のうち、どの rule id にも対応しないもの。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_hook_env(
                root, runtimes=["claude"],
                hook_text="custom_orphan_example() {\n  :\n}\n",
            )
            errors = danger_rules._check_enforcement_channels([], root)
        self.assertTrue(any("orphan_example" in e for e in errors), errors)

    def test_omp_has_hook_channel_for_ere_block_rules(self):
        """omp は omp-denial-reason.js 経由で block-dangerous-in-bash.sh を実行するので、
        match.ere を持つ block rule は glob（bash.patterns）無しでも enforcement channel を持つ。"""
        rule = {"id": "x", "action": "block", "impl": "table", "targets": ["omp"], "match": {"ere": "git remote"}}
        self.assertTrue(danger_rules._has_enforcement_channel(rule, "omp", {"omp"}, set()))
        # hook-pipeline.json が omp を配線していなければ経路なし
        self.assertFalse(danger_rules._has_enforcement_channel(rule, "omp", {"claude"}, set()))
        # 現行 table: omp を targets に持つ ere-only rule が実在する（git-remote）
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(encoding="utf-8")
        )
        git_remote = next(r for r in table["rules"] if r["id"] == "git-remote")
        self.assertIn("omp", git_remote["targets"])
        self.assertNotIn("omp", git_remote["match"].get("globs", {}))

    def test_real_repo_table_has_no_enforcement_gaps(self):
        # (e) 現行 table（core + extras）が 0 error で通ることの統合テスト。
        table = json.loads(
            (_REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                encoding="utf-8"
            )
        )
        errors = danger_rules._check_enforcement_channels_table(table, _REPO_ROOT)
        self.assertEqual(errors, [], errors)


class SyncAutoModeRulesCheckTestCase(unittest.TestCase):
    """scripts/sync-auto-mode-rules.py --check の drift 検出テスト（subprocess 統合テスト）。"""

    _SCRIPT_PATH = Path(__file__).resolve().parent.parent / "sync-auto-mode-rules.py"

    def _make_repo(self, tmp: Path, auto_mode: dict | None) -> Path:
        root = Path(tmp)
        policy_dir = root / "packages" / "core" / "policy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "danger-rules.json").write_text(json.dumps({
            "version": 1,
            "rules": [
                {"id": "rule-a", "autoMode": [{"tier": "hard_deny", "prose": "H"}]},
                {"id": "rule-b", "autoMode": [{"tier": "soft_deny", "prose": "S"}]},
            ],
        }), encoding="utf-8")

        settings_data = {"permissions": {}, "model": "x"}
        if auto_mode is not None:
            settings_data["autoMode"] = auto_mode
        (root / "packages" / "core" / "settings.json").write_text(
            json.dumps(settings_data), encoding="utf-8"
        )
        return root

    def _run_check(self, root: Path) -> tuple:
        result = subprocess.run(
            [sys.executable, str(self._SCRIPT_PATH), "--check", "--repo-root", str(root)],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def test_exits_1_when_settings_is_out_of_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(tmp, auto_mode=None)
            code, output = self._run_check(root)
        self.assertEqual(code, 1, output)

    def test_exits_0_when_settings_is_in_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(tmp, auto_mode={
                "hard_deny": ["$defaults", "H"],
                "soft_deny": ["$defaults", "S"],
            })
            code, output = self._run_check(root)
        self.assertEqual(code, 0, output)


class IntegrationTestCase(unittest.TestCase):
    """実リポジトリの danger-rules.json が全 source と矛盾しないか検証する（統合テスト）。"""

    def test_returns_empty_for_real_repo(self):
        errors = danger_rules.check(_REPO_ROOT)
        self.assertEqual(errors, [], msg="\n".join(e.message for e in errors))


class PosixEreContractTestCase(unittest.TestCase):
    """match.ere は bash =~（libc POSIX ERE）で判定されるため GNU 拡張エスケープを禁止する。"""

    def _table_with_ere(self, ere: str) -> dict:
        return {
            "version": 1,
            "constants": {
                "originEre": "x", "chainOnlyOriginEre": "x",
                "wordEndEre": "x", "originJs": "x",
            },
            "rules": [{
                "id": "sample-rule", "action": "block", "impl": "table",
                "targets": ["claude"], "message": "m",
                "match": {"ere": ere},
            }],
        }

    def test_posix_only_ere_passes(self):
        table = self._table_with_ere("(git|rtk git)[[:space:]]+push([^A-Za-z0-9_]|$)")
        self.assertEqual(
            [e for e in danger_rules._validate_schema(table, _REPO_ROOT) if "POSIX" in e], []
        )

    def test_backreference_is_rejected(self):
        # grep -E は (a)\1 を受けるが bash =~ では未定義（macOS では aa に一致しない）
        errors = danger_rules._validate_schema(self._table_with_ere("(rm)[[:space:]]+\\1"), _REPO_ROOT)
        self.assertTrue(any("POSIX" in e and "\\1" in e for e in errors), errors)

    def test_escaped_backslash_before_digit_is_a_literal_not_a_backreference(self):
        # `\\1` はリテラルの \ と 1。後方参照 `\1` と混同して弾かない（codex review）
        errors = danger_rules._validate_schema(self._table_with_ere("printf[[:space:]]+\\\\1"), _REPO_ROOT)
        self.assertEqual([e for e in errors if "POSIX" in e], [], errors)
        # 3 連（エスケープされた \ の後に本物の後方参照）は弾く
        errors = danger_rules._validate_schema(self._table_with_ere("(a)\\\\\\1"), _REPO_ROOT)
        self.assertTrue(any("POSIX" in e and "\\1" in e for e in errors), errors)

    def test_bash_consumed_constants_are_checked(self):
        table = self._table_with_ere("git push")
        table["constants"]["wordEndEre"] = "\\b"
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("constants.wordEndEre" in e and "\\b" in e for e in errors), errors)
        # originJs は pi extension（JS 正規表現）向けなので \\b を許す
        table = self._table_with_ere("git push")
        table["constants"]["originJs"] = "\\bgit"
        self.assertEqual(
            [e for e in danger_rules._validate_schema(table, _REPO_ROOT) if "POSIX" in e], []
        )

    def test_gnu_word_boundary_is_rejected_in_core_and_extras(self):
        table = self._table_with_ere("--no-verify\\b")
        errors = danger_rules._validate_schema(table, _REPO_ROOT)
        self.assertTrue(any("POSIX" in e and "\\b" in e for e in errors), errors)

        extra = {"version": 1, "rules": [{
            "id": "extras-rule", "action": "block", "impl": "table",
            "targets": ["claude"], "message": "m",
            "match": {"ere": "rm\\s+-rf"},
        }]}
        errors = danger_rules._validate_extra_table(extra, core_ids=set(), repo_root=_REPO_ROOT)
        self.assertTrue(any(e.startswith("extra-schema[extras-rule]") and "\\s" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()

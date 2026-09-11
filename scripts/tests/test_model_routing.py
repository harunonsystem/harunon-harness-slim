"""model routing の SSOT table と各 projection の契約を検証する。

役割別の model / effort は packages/core/model-routing.json（SSOT table）が持ち、
各 runtime の宣言ファイルはその投影。ここでは
  (a) table 自体の不変条件（schema・逸脱理由・(runtime, role) 一意）
  (b) format ごとの投影（table → 宣言ファイルに書く値）
  (c) checked-in の宣言ファイルが table と一致し、sync が byte-identical に再生成すること
  (d) 投影対象外の契約（settingsSync が routing キーを push すること、pi の package pin、
      omp の散文と config.yml の整合、runbook）
を見る。宣言ファイルの model id を文字列で直接アサートしない（それは table の仕事）。
"""

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib import model_routing as mr  # noqa: E402

SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync-model-routing.py"


def _mirror_repo(destination: Path, table: dict) -> None:
    """table + schema + 全 projection 先だけを temp repo へ複製する。"""
    for rel in (mr.TABLE_PATH, "schemas/model-routing.schema.json"):
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)
    for route in table["routes"]:
        for projection in route["projections"]:
            target = destination / projection["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / projection["path"], target)


def _projection_paths(table: dict) -> list[str]:
    return sorted({p["path"] for route in table["routes"] for p in route["projections"]})


class TestTableInvariants(unittest.TestCase):
    """(a) model-routing.json 自体の不変条件。"""

    def setUp(self):
        self.table = mr.load(REPO_ROOT)

    def test_committed_table_is_valid(self):
        self.assertEqual(mr._validate_table(self.table, REPO_ROOT), [])

    def test_only_sol_and_luna_are_routable(self):
        # Terra は標準ルートに置かない（ADR-010）。Astra も置かない: team plan では 5h/45 msgs の
        # 別枠で default に据えると枠を使い切るため、picker での手動選択に戻した（同日撤回）。
        self.assertEqual(set(self.table["models"]), {"sol", "luna"})
        self.assertNotIn("terra", " ".join(self.table["models"].values()))
        self.assertNotIn("astra", " ".join(self.table["models"].values()))

    def test_every_runtime_role_pair_is_unique(self):
        pairs = [(r["runtime"], r["role"]) for r in self.table["routes"]]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_duplicate_runtime_role_is_rejected(self):
        table = copy.deepcopy(self.table)
        table["routes"].append(copy.deepcopy(table["routes"][0]))
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("重複" in e for e in errors), errors)

    def test_deviation_from_purpose_default_requires_reason(self):
        table = copy.deepcopy(self.table)
        route = next(r for r in table["routes"] if r["runtime"] == "pi" and r["role"] == "default")
        self.assertEqual((route["model"], route["effort"]), ("luna", "medium"), "前提: pi default は Luna medium の逸脱")
        del route["reason"]
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("pi/default" in e and "reason" in e for e in errors), errors)

    def test_reason_on_non_deviating_route_is_rejected(self):
        table = copy.deepcopy(self.table)
        route = next(r for r in table["routes"] if r["runtime"] == "codex" and r["role"] == "worker")
        route["reason"] = "stale"
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("codex/worker" in e and "reason" in e for e in errors), errors)

    def test_unknown_model_alias_is_rejected(self):
        table = copy.deepcopy(self.table)
        table["routes"][0]["model"] = "terra"
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("terra" in e for e in errors), errors)

    def test_frontmatter_projection_requires_provider(self):
        table = copy.deepcopy(self.table)
        route = next(r for r in table["routes"] if r["runtime"] == "pi" and r["role"] == "scout")
        del route["projections"][0]["provider"]
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("provider" in e for e in errors), errors)

    def test_schema_rejects_unknown_effort(self):
        table = copy.deepcopy(self.table)
        table["routes"][0]["effort"] = "ultra"
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any(e.startswith("schema:") and "effort" in e for e in errors), errors)

    def test_two_routes_writing_the_same_path_and_key_are_rejected(self):
        """MR-001: 同じ (path, key) を 2 route が投影すると後勝ちで黙って上書きされるので拒否する。"""
        table = copy.deepcopy(self.table)
        worker = next(r for r in table["routes"] if r["runtime"] == "codex" and r["role"] == "worker")
        clone = copy.deepcopy(worker)
        clone["role"] = "worker-dup"
        table["routes"].append(clone)
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(
            any("codex/worker-dup" in e and "同じ (path, key)" in e and "model" in e for e in errors), errors
        )

    def test_key_shape_must_match_format(self):
        """MR-002: reader（dotted 解決）と renderer（行特定）が同じ行を指す形だけを許す。"""
        cases = {
            ("omp", "plan"): ("modelKey", "plan", "modelRoles.<role>"),
            ("pi", "scout"): ("modelKey", "openai.model", "トップレベル名"),
            ("codex", "default"): ("modelKey", "agents..model", "dotted"),
            ("pi", "default"): ("providerKey", "defaultProvider.", "dotted"),
        }
        for (runtime, role), (field, bad_key, fragment) in cases.items():
            with self.subTest(runtime=runtime, role=role, key=bad_key):
                table = copy.deepcopy(self.table)
                route = next(r for r in table["routes"] if r["runtime"] == runtime and r["role"] == role)
                route["projections"][0][field] = bad_key
                errors = mr._validate_table(table, REPO_ROOT)
                self.assertTrue(any(repr(bad_key) in e and fragment in e for e in errors), errors)

    def test_projection_path_must_live_under_the_route_runtime_target(self):
        """MR-003: opencode の route が pi のファイルを書くような取り違えを拒否する。"""
        table = copy.deepcopy(self.table)
        route = next(r for r in table["routes"] if r["runtime"] == "opencode")
        route["projections"][0]["path"] = "packages/targets/pi/agents/reviewer.md"
        errors = mr._validate_table(table, REPO_ROOT)
        self.assertTrue(any("packages/targets/opencode/" in e and "配下" in e for e in errors), errors)


class TestProjectionRendering(unittest.TestCase):
    """(b) format ごとに table → 宣言ファイルの値がどう描かれるか。"""

    TABLE = {
        "models": {"sol": "gpt-5.6-sol", "luna": "gpt-5.6-luna"},
    }

    def test_toml_writes_bare_model_and_every_effort_key(self):
        route = {"model": "luna", "effort": "max"}
        projection = {"format": "toml", "modelKey": "model", "effortKeys": ["model_reasoning_effort", "plan_mode_reasoning_effort"]}
        self.assertEqual(
            mr.expected_values(self.TABLE, route, projection),
            {"model": "gpt-5.6-luna", "model_reasoning_effort": "max", "plan_mode_reasoning_effort": "max"},
        )

    def test_json_writes_bare_model_and_provider_separately(self):
        route = {"model": "luna", "effort": "medium"}
        projection = {
            "format": "json", "provider": "openai-codex", "providerKey": "defaultProvider",
            "modelKey": "defaultModel", "effortKeys": ["defaultThinkingLevel"],
        }
        self.assertEqual(
            mr.expected_values(self.TABLE, route, projection),
            {"defaultModel": "gpt-5.6-luna", "defaultThinkingLevel": "medium", "defaultProvider": "openai-codex"},
        )

    def test_frontmatter_prefixes_provider(self):
        route = {"model": "sol", "effort": "medium"}
        projection = {"format": "frontmatter", "provider": "openai", "modelKey": "model", "effortKeys": ["reasoningEffort"]}
        self.assertEqual(
            mr.expected_values(self.TABLE, route, projection),
            {"model": "openai/gpt-5.6-sol", "reasoningEffort": "medium"},
        )

    def test_omp_roles_combines_provider_model_and_effort(self):
        route = {"model": "luna", "effort": "max"}
        projection = {"format": "omp-roles", "provider": "openai-codex", "modelKey": "modelRoles.plan", "effortKeys": []}
        self.assertEqual(
            mr.expected_values(self.TABLE, route, projection),
            {"modelRoles.plan": "openai-codex/gpt-5.6-luna:max"},
        )

    def test_render_replaces_only_the_value_in_each_format(self):
        cases = [
            ("toml", {"modelKey": "model", "effortKeys": ["model_reasoning_effort"]},
             '# c\nmodel = "old"\nreview_model = "keep"\nmodel_reasoning_effort = "low"\n',
             '# c\nmodel = "new"\nreview_model = "keep"\nmodel_reasoning_effort = "max"\n'),
            ("json", {"modelKey": "defaultModel", "effortKeys": ["defaultThinkingLevel"]},
             '{\n\t"defaultModel": "old",\n\t"defaultThinkingLevel": "low",\n\t"theme": "dark"\n}\n',
             '{\n\t"defaultModel": "new",\n\t"defaultThinkingLevel": "max",\n\t"theme": "dark"\n}\n'),
            ("frontmatter", {"modelKey": "model", "effortKeys": ["thinking"]},
             "---\nname: x\nmodel: old\nthinking: low\n---\n\nmodel: body-text-untouched\n",
             "---\nname: x\nmodel: new\nthinking: max\n---\n\nmodel: body-text-untouched\n"),
            ("omp-roles", {"modelKey": "modelRoles.plan", "effortKeys": []},
             "modelRoles:\n  default: a\n  plan: old\nplan:\n  enabled: true\n",
             "modelRoles:\n  default: a\n  plan: new\nplan:\n  enabled: true\n"),
        ]
        for fmt, projection, before, after in cases:
            with self.subTest(fmt=fmt):
                projection = {"format": fmt, "path": f"x.{fmt}", **projection}
                values = {projection["modelKey"]: "new", **{k: "max" for k in projection["effortKeys"]}}
                self.assertEqual(mr.render(before, projection, values), after)

    def test_render_refuses_ambiguous_or_missing_lines(self):
        projection = {"format": "toml", "path": "x.toml", "modelKey": "model", "effortKeys": []}
        with self.assertRaises(ValueError):
            mr.render('model = "a"\nmodel = "b"\n', projection, {"model": "c"})
        with self.assertRaises(ValueError):
            mr.render('other = "a"\n', projection, {"model": "c"})


class TestCommittedFilesMatchTable(unittest.TestCase):
    """(c) 宣言ファイルは table の投影であること。"""

    def setUp(self):
        self.table = mr.load(REPO_ROOT)

    def test_validate_harness_check_is_clean(self):
        self.assertEqual(mr.check(REPO_ROOT), [])

    def test_sync_regenerates_committed_files_byte_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root, self.table)
            result = subprocess.run(
                [sys.executable, str(SYNC_SCRIPT), "--repo-root", str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for rel in _projection_paths(self.table):
                self.assertEqual(
                    (root / rel).read_bytes(), (REPO_ROOT / rel).read_bytes(), rel
                )

    def test_drift_in_a_declaration_file_is_detected_and_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root, self.table)
            target = root / "packages/targets/codex/agents/worker.toml"
            original = target.read_text(encoding="utf-8")
            target.write_text(original.replace('model = "gpt-5.6-luna"', 'model = "gpt-5.6-sol"'), encoding="utf-8")

            findings = mr.check(root)
            self.assertTrue(
                any("codex/worker" in f.message and "sync-model-routing.py" in f.message for f in findings),
                [f.message for f in findings],
            )
            check = subprocess.run(
                [sys.executable, str(SYNC_SCRIPT), "--check", "--repo-root", str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(check.returncode, 1, check.stdout)

            changed = mr.apply(self.table, root)
            self.assertEqual([p.relative_to(root).as_posix() for p in changed], ["packages/targets/codex/agents/worker.toml"])
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(mr.check(root), [])

    def test_apply_writes_nothing_when_any_render_fails(self):
        """MR-004: 後ろの projection が render に失敗したら、前のファイルの drift も直さない（部分更新を残さない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root, self.table)
            drifted = root / "packages/targets/codex/agents/worker.toml"
            drifted_text = drifted.read_text(encoding="utf-8").replace('model = "gpt-5.6-luna"', 'model = "gpt-5.6-sol"')
            drifted.write_text(drifted_text, encoding="utf-8")
            broken = root / "packages/targets/omp/config.yml"
            broken.write_text(broken.read_text(encoding="utf-8").replace("modelRoles:", "roles:"), encoding="utf-8")

            with self.assertRaises(ValueError):
                mr.apply(self.table, root)
            self.assertEqual(drifted.read_text(encoding="utf-8"), drifted_text, "失敗した apply が別ファイルを書いた")

    def test_foreign_model_id_in_declaration_file_is_rejected(self):
        """table 外の model id が projection の model key に紛れ込むことを拒否する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mirror_repo(root, self.table)
            route, projection = next(
                (route, projection)
                for route in self.table["routes"]
                for projection in route["projections"]
                if projection["path"] == "packages/targets/omp/config.yml"
            )
            target = root / projection["path"]
            expected = mr.expected_values(self.table, route, projection)[projection["modelKey"]]
            foreign = f"{projection['provider']}/foreign-model:{route['effort']}"
            target.write_text(target.read_text(encoding="utf-8").replace(expected, foreign, 1), encoding="utf-8")
            findings = mr.check(root)
            self.assertTrue(any("foreign-model" in f.message for f in findings), [f.message for f in findings])

    def test_table_covers_every_model_bearing_declaration_file(self):
        """packages/targets 配下で model id を持つ設定ファイルは全て table の投影先であること。

        散文（AGENTS.md / config.json の notes）は投影対象外なので除く。
        """
        model_ids = tuple(self.table["models"].values())
        bearing = set()
        for path in (REPO_ROOT / "packages" / "targets").rglob("*"):
            if not path.is_file() or path.suffix not in {".toml", ".yml", ".json", ".md"}:
                continue
            if path.name in {"AGENTS.md", "config.json"}:
                continue
            if any(model_id in path.read_text(encoding="utf-8") for model_id in model_ids):
                bearing.add(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(bearing, set(_projection_paths(self.table)))


class TestRoutingAdjacentContracts(unittest.TestCase):
    """(d) table の投影対象ではないが routing と一体の契約。"""

    def read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def test_codex_settings_sync_pushes_routing_keys(self):
        """Codex app 再起動時の medium へのリセットを防ぐため push 同期する。"""
        sync = json.loads(self.read("packages/targets/codex/config.json"))["settingsSync"]
        for key in (
            "model",
            "model_reasoning_effort",
            "plan_mode_reasoning_effort",
            "agents.default_subagent_model",
            "agents.default_subagent_reasoning_effort",
        ):
            self.assertIn(key, sync["keys"], key)
        # features.* は feature table からの導出（config.json に直接列挙しない）。
        from harness_lib.config import load_target
        from harness_lib.settings_sync import _computed_feature_keys

        declared, retired = _computed_feature_keys(load_target("codex", REPO_ROOT), REPO_ROOT)
        self.assertNotIn("features.voice_transcription", declared)
        self.assertIn("features.voice_transcription", retired)
        self.assertNotIn("model_catalog_json", sync["localKeys"])
        self.assertIn("model_catalog_json", sync["removeKeys"])
        self.assertNotIn("voice_transcription", self.read("packages/targets/codex/config.toml"))

    def test_omp_settings_sync_pushes_model_roles(self):
        target = json.loads(self.read("packages/targets/omp/config.json"))
        self.assertIn("modelRoles", target["settingsSync"]["keys"])
        self.assertIn("hideThinkingBlock", target["settingsSync"]["keys"])
        self.assertIn("display.hideToolActivity", target["settingsSync"]["keys"])
        config = self.read("packages/targets/omp/config.yml")
        self.assertIn("  - openai-codex/*", config)
        self.assertIn("hideThinkingBlock: true", config)
        self.assertIn("hideToolActivity: true", config)

    def test_pi_settings_pin_packages_and_compaction(self):
        settings = json.loads(self.read("packages/targets/pi/settings.json"))
        self.assertTrue(settings["hideThinkingBlock"])
        self.assertEqual(settings["compaction"], {
            "enabled": True,
            "reserveTokens": 16384,
            "keepRecentTokens": 20000,
        })
        packages = settings["packages"]
        # Package versions are upgraded independently; the contract here is that
        # these integrations stay explicitly pinned to a concrete semver.
        for package_name in (
            "@howaboua/pi-codex-conversion",
            "@gotgenes/pi-subagents",
            "pi-web-access",
            "pi-mcp-adapter",
        ):
            with self.subTest(package=package_name):
                matches = [
                    package for package in packages
                    if package.startswith(f"npm:{package_name}@")
                ]
                self.assertEqual(len(matches), 1, matches)
                self.assertRegex(
                    matches[0],
                    rf"^npm:{re.escape(package_name)}@\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$",
                )
        self.assertNotIn("pi-code-reviewer", " ".join(packages))
        self.assertNotIn("pi-observational-memory", " ".join(packages))

    def test_pi_compaction_does_not_leave_stale_adapter_helpers(self):
        conversion = json.loads(self.read("packages/targets/pi/pi-codex-conversion.json"))
        self.assertTrue(conversion["ui"]["compactTools"])
        self.assertTrue(conversion["compaction"]["responsesCompaction"])
        self.assertNotIn("compactionModel", conversion["openai"])
        self.assertNotIn("compactionReasoning", conversion["openai"])

    def test_pi_coding_profile_uses_codex_web_run_as_canonical_search(self):
        web_search = json.loads(self.read("packages/targets/pi/web-search.json"))
        self.assertFalse(web_search["webSearch"]["enabled"])
        target = json.loads(self.read("packages/targets/pi/config.json"))
        self.assertEqual(
            target["distribute"]["web-search.json"]["source"],
            "packages/targets/pi/web-search.json",
        )

    def test_pi_agents_use_thinking_not_thinking_level(self):
        """@gotgenes/pi-subagents の frontmatter キーは thinking（@narumitw の thinkingLevel から改名）。"""
        for path in (REPO_ROOT / "packages/targets/pi/agents").glob("*.md"):
            frontmatter = path.read_text(encoding="utf-8").split("---", 2)[1]
            self.assertNotIn("thinkingLevel:", frontmatter, path.name)

    def test_review_agents_are_bounded(self):
        self.assertIn("steps: 8", self.read("packages/targets/opencode/agents/reviewer.md"))

    def test_omp_prose_contracts_match_config_roles(self):
        """AGENTS.md / config.json の説明文が config.yml の role 実体と矛盾しないこと。

        config.yml だけ変えて配布指示（AGENTS.md）や notes を放置すると、
        omp セッションは実設定と異なるモデルへの委譲を指示され続ける
        （2026-08-20 のモデル統一で実際に発生し、codex review が検出した）。
        """
        model_token = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+")
        declared = set(model_token.findall(self.read("packages/targets/omp/config.yml")))
        for relative in (
            "packages/targets/omp/AGENTS.md",
            "packages/targets/omp/config.json",
        ):
            mentioned = set(model_token.findall(self.read(relative)))
            self.assertLessEqual(
                mentioned,
                declared,
                msg=f"{relative} が config.yml に無い model:thinking を説明している",
            )

    def test_doctor_and_runbook_require_explicit_fallback(self):
        doctor = self.read("scripts/harness-doctor.sh")
        runbook = self.read("docs/adr/010-sol-luna-routing.md")
        self.assertIn("自動 fallback はしません", doctor)
        self.assertIn("fallback は明示的な --model 指定", doctor)
        self.assertIn("Subscription termination runbook", runbook)
        self.assertIn("pi --model opencode-zen/mimo-v2.5-free", runbook)
        self.assertIn("omp --model opencode-zen/mimo-v2.5-free", runbook)


if __name__ == "__main__":
    unittest.main()

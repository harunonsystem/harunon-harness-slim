#!/usr/bin/env python3
"""validate-harness.py のテスト。"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib import capabilities  # noqa: E402
from harness_lib.validators import (  # noqa: E402
    budget,
    context_md,
    distribution_sources,
    plans,
    references,
    skills,
    workflow_contract,
)


def _load_validate_harness():
    spec = importlib.util.spec_from_file_location(
        "validate_harness", SCRIPTS_DIR / "validate-harness.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["validate_harness"] = module
    spec.loader.exec_module(module)
    return module


vh = _load_validate_harness()


def _copy_workflow_contract(root: Path) -> None:
    """packages/core/policy/workflow-contract.json を root にコピーする（SSOT テーブル）。"""
    dst = root / "packages" / "core" / "policy" / "workflow-contract.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (REPO_ROOT / "packages" / "core" / "policy" / "workflow-contract.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


class TestCoreWorkflowContract(unittest.TestCase):
    def test_rejects_transition_to_unknown_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "packages" / "core" / "workflows"
            policy = root / "packages" / "core" / "policy"
            workflows.mkdir(parents=True)
            policy.mkdir(parents=True)
            _copy_workflow_contract(root)
            (workflows / "change.json").write_text(
                json.dumps(
                    {
                        "name": "change",
                        "initialState": "intake",
                        "states": {
                            "intake": {"start": "missing"},
                            "complete": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (workflows / "task-state.schema.json").write_text("{}\n", encoding="utf-8")
            (policy / "harnessctl.py").write_text("# policy kernel\n", encoding="utf-8")

            findings = workflow_contract.check_core_workflow_contract(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("missing", findings[0].message)

    def test_requires_every_target_to_distribute_policy_and_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "packages" / "core" / "workflows"
            policy = root / "packages" / "core" / "policy"
            target = root / "packages" / "targets" / "codex"
            workflows.mkdir(parents=True)
            policy.mkdir(parents=True)
            target.mkdir(parents=True)
            _copy_workflow_contract(root)
            (workflows / "change.json").write_text(
                json.dumps(
                    {
                        "name": "change",
                        "initialState": "intake",
                        "states": {"intake": {"done": "complete"}, "complete": {}},
                    }
                ),
                encoding="utf-8",
            )
            (workflows / "task-state.schema.json").write_text("{}\n", encoding="utf-8")
            (policy / "harnessctl.py").write_text("# policy kernel\n", encoding="utf-8")
            (target / "config.json").write_text(
                json.dumps({"distribute": {}}), encoding="utf-8"
            )

            findings = workflow_contract.check_core_workflow_contract(root)

            messages = [finding.message for finding in findings]
            self.assertTrue(any("policy/" in message for message in messages))
            self.assertTrue(any("workflows/" in message for message in messages))

    def test_run_change_uses_the_shared_agents_kernel_distribution(self):
        config = json.loads(
            (REPO_ROOT / "packages/targets/shared-agents/config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["distribute"]["policy/"]["source"], "packages/core/policy/")
        adapter = (
            REPO_ROOT / "packages/core/skills/run-change/scripts/harness.py"
        ).read_text(encoding="utf-8")
        self.assertIn('parents[3] / "policy/harnessctl.py"', adapter)

    def test_opencode_workflows_are_distributed_next_to_runtime_kernel(self):
        config = json.loads(
            (REPO_ROOT / "packages/targets/opencode/config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            config["distribute"]["runtime/workflows/"]["source"],
            "packages/core/workflows/",
        )
        self.assertNotIn("workflows/", config["distribute"])

    def test_every_target_distributes_a_native_policy_gate(self):
        findings = workflow_contract.check_core_workflow_contract(REPO_ROOT)

        self.assertFalse(
            [finding for finding in findings if "Core Workflow gate" in finding.message]
        )

    def test_reports_missing_gate_distribution_pair(self):
        """workflow-contract.json の gateDistribution に宣言された destination/source が
        config.json に無ければ core-workflow-contract エラーとして報告される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "packages" / "core" / "workflows"
            policy = root / "packages" / "core" / "policy"
            target = root / "packages" / "targets" / "claude"
            workflows.mkdir(parents=True)
            policy.mkdir(parents=True)
            target.mkdir(parents=True)
            (workflows / "change.json").write_text(
                json.dumps(
                    {
                        "name": "change",
                        "initialState": "intake",
                        "states": {"intake": {"done": "complete"}, "complete": {}},
                    }
                ),
                encoding="utf-8",
            )
            (workflows / "task-state.schema.json").write_text("{}\n", encoding="utf-8")
            (policy / "harnessctl.py").write_text("# policy kernel\n", encoding="utf-8")
            _copy_workflow_contract(root)
            (target / "config.json").write_text(
                json.dumps({
                    "name": "claude",
                    "distribute": {
                        "policy/": {"source": "packages/core/policy/"},
                        "workflows/": {"source": "packages/core/workflows/"},
                        # hooks/ が欠落している = claude の gate 配布契約違反
                    },
                }),
                encoding="utf-8",
            )

            findings = workflow_contract.check_core_workflow_contract(root)

            gate_messages = [f for f in findings if "Core Workflow gate" in f.message]
            self.assertEqual(len(gate_messages), 1)
            self.assertIn("hooks/", gate_messages[0].message)


class TestAgentsMdBudget(unittest.TestCase):
    """AGENTS.md は常駐予算（文字数）と runtime の読み込み上限（bytes）の 2 本で見る。"""

    def test_small_agents_md_has_no_findings(self):
        self.assertEqual(budget.agents_md_findings("codex", b"# tiny\n"), [])

    def test_codex_agents_md_at_project_doc_limit_is_error(self):
        limit = budget.PROJECT_DOC_HARD_LIMIT_BYTES["codex"]
        findings = budget.agents_md_findings("codex", b"x" * limit)
        checks = {f.check: f.level for f in findings}
        self.assertEqual(checks.get("project-doc-hard-limit"), "error")
        # 文字数予算にも当たる（上限は予算のはるか先にある）
        self.assertEqual(checks.get("target-residency-budget"), "error")

    def test_hard_limit_only_applies_to_runtimes_with_a_known_limit(self):
        limit = budget.PROJECT_DOC_HARD_LIMIT_BYTES["codex"]
        findings = budget.agents_md_findings("pi", b"x" * limit)
        self.assertNotIn("project-doc-hard-limit", {f.check for f in findings})

    def test_real_targets_stay_under_the_hard_limit(self):
        hard = [
            f for f in budget.check_target_residency_budget(REPO_ROOT)
            if f.check == "project-doc-hard-limit"
        ]
        self.assertEqual(hard, [])


class TestCapabilityContract(unittest.TestCase):
    def test_real_repo_capability_contract_is_clean(self):
        findings = capabilities.check(REPO_ROOT)

        self.assertEqual(findings, [])

    def test_wraps_capability_library_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = capabilities.check(Path(tmp))

            self.assertTrue(findings)
            self.assertTrue(all(finding.check == "capability-contract" for finding in findings))
            self.assertTrue(any(finding.code == "schema" for finding in findings))


class TestTargetConfigSources(unittest.TestCase):
    def test_returns_error_when_distribute_source_missing(self):

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            (targets / "config.json").write_text(
                '{"distribute": {"missing.md": {"source": "packages/core/missing.md"}}}'
                "\n",
                encoding="utf-8",
            )

            findings = distribution_sources.check_target_config_sources(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("missing.md", findings[0].message)


    def test_returns_error_for_missing_element_in_array_source(self):

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            existing = root / "packages" / "core" / "rules"
            existing.mkdir(parents=True)
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": '
                '["packages/core/rules/", "packages/extras/_active/rules/"]}}}'
                "\n",
                encoding="utf-8",
            )

            findings = distribution_sources.check_target_config_sources(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("packages/extras/_active/rules/", findings[0].message)

    def test_downgrades_to_warn_when_source_is_in_uninitialized_submodule(self):

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            (root / "packages" / "core" / "rules").mkdir(parents=True)
            # 未取得 submodule = .gitmodules に宣言されているが中身が空
            (root / "packages" / "extras" / "_active").mkdir(parents=True)
            (root / ".gitmodules").write_text(
                '[submodule "packages/extras/_active"]\n'
                "\tpath = packages/extras/_active\n"
                "\turl = git@example.com:x/y.git\n",
                encoding="utf-8",
            )
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": '
                '["packages/core/rules/", "packages/extras/_active/rules/"]}}}'
                "\n",
                encoding="utf-8",
            )

            findings = distribution_sources.check_target_config_sources(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "warn")
            self.assertIn("submodule", findings[0].message)

    def test_returns_no_findings_when_all_array_sources_exist(self):

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            for d in ("core/rules", "extras/_active/rules"):
                (root / "packages" / d).mkdir(parents=True)
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": '
                '["packages/core/rules/", "packages/extras/_active/rules/"]}}}'
                "\n",
                encoding="utf-8",
            )

            findings = distribution_sources.check_target_config_sources(root)

            self.assertEqual(findings, [])


class TestNoSymlinksInDistributionSources(unittest.TestCase):
    def test_returns_error_when_source_dir_contains_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            rules_dir = root / "packages" / "core" / "rules"
            rules_dir.mkdir(parents=True)
            real_file = root / "outside.md"
            real_file.write_text("x", encoding="utf-8")
            (rules_dir / "linked.md").symlink_to(real_file)
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": "packages/core/rules/"}}}\n',
                encoding="utf-8",
            )

            findings = distribution_sources.check_no_symlinks_in_distribution_sources(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("linked.md", findings[0].message)

    def test_returns_no_findings_when_source_dir_has_no_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            rules_dir = root / "packages" / "core" / "rules"
            rules_dir.mkdir(parents=True)
            (rules_dir / "normal.md").write_text("x", encoding="utf-8")
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": "packages/core/rules/"}}}\n',
                encoding="utf-8",
            )

            findings = distribution_sources.check_no_symlinks_in_distribution_sources(root)

            self.assertEqual(findings, [])

    def test_ignores_missing_source_dir(self):
        """未取得 submodule 等で source ディレクトリが存在しない場合は対象外。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            (targets / "config.json").write_text(
                '{"distribute": {"rules/": {"source": '
                '["packages/core/rules/", "packages/extras/_active/rules/"]}}}\n',
                encoding="utf-8",
            )
            (root / "packages" / "core" / "rules").mkdir(parents=True)

            findings = distribution_sources.check_no_symlinks_in_distribution_sources(root)

            self.assertEqual(findings, [])

    def test_ignores_single_file_source(self):
        """単一ファイル source（ディレクトリでない）は対象外。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "packages" / "targets" / "claude"
            targets.mkdir(parents=True)
            core = root / "packages" / "core"
            core.mkdir(parents=True)
            real_file = root / "outside.md"
            real_file.write_text("x", encoding="utf-8")
            (core / "CLAUDE.md").symlink_to(real_file)
            (targets / "config.json").write_text(
                '{"distribute": {"CLAUDE.md": {"source": "packages/core/CLAUDE.md"}}}\n',
                encoding="utf-8",
            )

            findings = distribution_sources.check_no_symlinks_in_distribution_sources(root)

            self.assertEqual(findings, [])


def _make_skill(root: Path, name: str, content: str, filename: str = "SKILL.md") -> None:
    skill = root / "packages" / "core" / "skills" / name
    skill.mkdir(parents=True)
    (skill / filename).write_text(content, encoding="utf-8")


class TestSkillMdCasing(unittest.TestCase):
    def test_returns_error_for_lowercase_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "good", "---\nname: good\n---\n")
            _make_skill(root, "bad", "---\nname: bad\n---\n", filename="skill.md")

            findings = skills.check_skill_md_casing(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("bad", findings[0].message)


class TestSkillFrontmatter(unittest.TestCase):
    def test_returns_error_when_frontmatter_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "no-fm", "# no-fm\n\nbody only\n")

            findings = skills.check_skill_frontmatter(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("no-fm", findings[0].message)

    def test_returns_error_when_name_mismatches_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "my-skill", "---\nname: other-name\n---\n")

            findings = skills.check_skill_frontmatter(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("other-name", findings[0].message)

    def test_allows_ckm_prefixed_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "vendored", "---\nname: ckm:vendored\n---\n")

            self.assertEqual(skills.check_skill_frontmatter(root), [])


class TestHooksWiring(unittest.TestCase):
    def _make_repo(self, root: Path, hook_files: list, wired: list) -> None:
        hooks_dir = root / "packages" / "core" / "hooks"
        hooks_dir.mkdir(parents=True)
        for f in hook_files:
            (hooks_dir / f).write_text("#!/bin/bash\n", encoding="utf-8")
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": f"~/.claude/hooks/{f}"}
                            for f in wired
                        ],
                    }
                ]
            }
        }
        (root / "packages" / "core" / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

    def test_returns_error_when_wired_hook_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root, ["a.sh"], ["a.sh", "ghost.sh"])

            findings = distribution_sources.check_hooks_wiring(root)

            errors = [f for f in findings if f.level == "error"]
            self.assertEqual(len(errors), 1)
            self.assertIn("ghost.sh", errors[0].message)

    def test_warns_for_unwired_hook_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root, ["a.sh", "orphan.sh"], ["a.sh"])

            findings = distribution_sources.check_hooks_wiring(root)

            warns = [f for f in findings if f.level == "warn"]
            self.assertEqual(len(warns), 1)
            self.assertIn("orphan.sh", warns[0].message)

    def test_manual_hooks_are_not_reported_as_unwired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root, ["a.sh", "codex-review-bypass.sh"], ["a.sh"])

            self.assertEqual(distribution_sources.check_hooks_wiring(root), [])


class TestContextScaleCounts(unittest.TestCase):
    def test_returns_error_when_core_skill_count_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "only-one", "---\nname: only-one\n---\n")
            (root / "docs" / "adr").mkdir(parents=True)
            (root / "CONTEXT.md").write_text(
                "| カテゴリ | core | extras |\n"
                "| --- | --- | --- |\n"
                "| skills | 2 | 8 |\n",
                encoding="utf-8",
            )

            findings = context_md.check_context_scale_counts(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("skills", findings[0].message)


def _make_targets_dirs(root: Path, names: list[str]) -> None:
    targets_dir = root / "packages" / "targets"
    for name in names:
        target = targets_dir / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}\n", encoding="utf-8")


class TestContextTargetTable(unittest.TestCase):
    def test_returns_no_findings_when_table_matches_target_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_targets_dirs(root, ["claude", "codex", "opencode", "omp"])
            (root / "CONTEXT.md").write_text(
                "| 項目 | Claude Code | Codex Desktop | OpenCode | omp |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 指示ファイル | CLAUDE.md | AGENTS.md | AGENTS.md | AGENTS.md |\n",
                encoding="utf-8",
            )

            self.assertEqual(context_md.check_context_target_table(root), [])

    def test_returns_error_when_target_dir_missing_from_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_targets_dirs(root, ["claude", "codex", "opencode", "omp"])
            (root / "CONTEXT.md").write_text(
                "| 項目 | Claude Code | Codex Desktop | OpenCode |\n"
                "| --- | --- | --- | --- |\n"
                "| 指示ファイル | CLAUDE.md | AGENTS.md | AGENTS.md |\n",
                encoding="utf-8",
            )

            findings = context_md.check_context_target_table(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("omp", findings[0].message)

    def test_returns_error_when_table_has_stale_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_targets_dirs(root, ["claude", "codex", "opencode"])
            (root / "CONTEXT.md").write_text(
                "| 項目 | Claude Code | Codex Desktop | OpenCode | pi |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 指示ファイル | CLAUDE.md | AGENTS.md | AGENTS.md | AGENTS.md |\n",
                encoding="utf-8",
            )

            findings = context_md.check_context_target_table(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("pi", findings[0].message)


def _make_always_loaded_core(
    root: Path, claude_size: int = 100, rtk_size: int = 100, headroom_size: int = 100
) -> Path:
    core = root / "packages" / "core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "CLAUDE.md").write_text("a" * claude_size, encoding="utf-8")
    (core / "RTK.md").write_text("a" * rtk_size, encoding="utf-8")
    (core / "HEADROOM.md").write_text("a" * headroom_size, encoding="utf-8")
    return core


class TestAlwaysLoadedBudget(unittest.TestCase):
    def test_returns_no_findings_when_under_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_always_loaded_core(root)

            self.assertEqual(budget.check_always_loaded_budget(root), [])

    def test_returns_warn_when_over_warn_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_always_loaded_core(root, claude_size=41_000)

            findings = budget.check_always_loaded_budget(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "warn")

    def test_returns_error_when_over_error_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_always_loaded_core(root, claude_size=49_000)

            findings = budget.check_always_loaded_budget(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")

    def test_excludes_paths_scoped_rules_from_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = _make_always_loaded_core(root)
            rules_dir = core / "rules"
            rules_dir.mkdir()
            (rules_dir / "project-specific.md").write_text(
                '---\npaths:\n  - "sandbox/**"\n---\n\n' + ("a" * 50_000),
                encoding="utf-8",
            )

            self.assertEqual(budget.check_always_loaded_budget(root), [])

    def test_counts_non_scoped_rules_toward_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = _make_always_loaded_core(root)
            rules_dir = core / "rules"
            rules_dir.mkdir()
            (rules_dir / "always-on.md").write_text("a" * 41_000, encoding="utf-8")

            findings = budget.check_always_loaded_budget(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "warn")


def _make_residency_target(
    root: Path,
    target_name: str = "testtarget",
    agents_chars: int = 100,
    skill_frontmatter_chars: list[int] | None = None,
) -> Path:
    """claude 以外の1ターゲット分の distribute 構成（AGENTS.md + skills/）を合成する。"""
    schema_dir = root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema_dst = schema_dir / "target-config.schema.json"
    if not schema_dst.is_file():
        schema_dst.write_bytes(
            (REPO_ROOT / "schemas" / "target-config.schema.json").read_bytes()
        )

    target_dir = root / "packages" / "targets" / target_name
    target_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "name": target_name,
        "displayName": target_name,
        "configDir": f"~/.{target_name}",
        "configFile": "",
        "instructionsFile": "AGENTS.md",
        "distribute": {
            "AGENTS.md": {"source": f"packages/targets/{target_name}/AGENTS.md"},
            "skills/": {"source": "packages/core/skills/"},
        }
    }
    (target_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (target_dir / "AGENTS.md").write_text("a" * agents_chars, encoding="utf-8")

    skills_dir = root / "packages" / "core" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for i, fm_chars in enumerate(skill_frontmatter_chars or [100]):
        skill_dir = skills_dir / f"skill{i}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        # frontmatter ブロック文字数 = len("---\n") + body + len("\n---") = body + 8
        body = "a" * max(fm_chars - 8, 1)
        (skill_dir / "SKILL.md").write_text(
            f"---\n{body}\n---\nSkill body\n", encoding="utf-8"
        )
    return target_dir


class TestTargetResidencyBudget(unittest.TestCase):
    def test_real_repo_targets_pass_budget(self):
        findings = budget.check_target_residency_budget(REPO_ROOT)

        errors = [f for f in findings if f.level == "error"]
        self.assertEqual(errors, [], f"実 repo で予算超過 error: {errors}")

    def test_returns_no_findings_when_under_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(root)

            self.assertEqual(budget.check_target_residency_budget(root), [])

    def test_returns_error_when_agents_md_bloats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(root, agents_chars=5_000)

            findings = budget.check_target_residency_budget(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("AGENTS.md", findings[0].message)

    def test_claude_frontmatter_warns_on_dedicated_budget(self):
        """claude は skill 本数が他ターゲットと桁違いなので専用予算で検証する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(
                root,
                target_name="claude",
                agents_chars=1,
                skill_frontmatter_chars=[10_000],
            )

            findings = budget.check_target_residency_budget(root)

            frontmatter = [f for f in findings if "frontmatter" in f.message]
            self.assertEqual(len(frontmatter), 1)
            self.assertEqual(frontmatter[0].level, "warn")

    def test_claude_frontmatter_errors_past_dedicated_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(
                root,
                target_name="claude",
                agents_chars=1,
                skill_frontmatter_chars=[12_000],
            )

            findings = budget.check_target_residency_budget(root)

            frontmatter = [f for f in findings if "frontmatter" in f.message]
            self.assertEqual(len(frontmatter), 1)
            self.assertEqual(frontmatter[0].level, "error")

    def test_claude_frontmatter_budget_is_looser_than_other_targets(self):
        """他ターゲットなら error になる量が claude では warn に収まる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(
                root, target_name="codex", agents_chars=1,
                skill_frontmatter_chars=[10_000],
            )
            codex = budget.check_target_residency_budget(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(
                root, target_name="claude", agents_chars=1,
                skill_frontmatter_chars=[10_000],
            )
            claude = budget.check_target_residency_budget(root)

        self.assertEqual([f.level for f in codex], ["error"])
        self.assertEqual([f.level for f in claude], ["warn"])

    def test_curated_skill_frontmatter_is_excluded_from_budget(self):
        """rulesync.lock 宣言の curated skill は harness が大きさを制御できないので数えない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_residency_target(root, skill_frontmatter_chars=[100, 20_000])
            (root / "rulesync.lock").write_text(
                json.dumps({"sources": {"up": {"skills": {"skill1": {}}}}}),
                encoding="utf-8",
            )

            self.assertEqual(budget.check_target_residency_budget(root), [])


class TestProseSkillReferences(unittest.TestCase):
    def test_returns_error_for_dangling_skill_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "real-skill", "---\nname: real-skill\n---\n")
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text(
                "違和感があれば `/ghost-skill` で確認。\n", encoding="utf-8"
            )

            findings = references.check_prose_skill_references(root)

            self.assertEqual(len(findings), 1)
            # extras 未取得時は warn に格下げ
            self.assertEqual(findings[0].level, "warn")
            self.assertIn("ghost-skill", findings[0].message)

    def test_detects_ghost_skill_as_error_when_extras_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "real-skill", "---\nname: real-skill\n---\n")
            extras_skills = root / "packages" / "extras" / "_active" / "skills"
            extras_skills.mkdir(parents=True)
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text(
                "違和感があれば `/ghost-skill` で確認。\n", encoding="utf-8"
            )

            findings = references.check_prose_skill_references(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("ghost-skill", findings[0].message)

    def test_allows_existing_skill_and_namespaced_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "real-skill", "---\nname: real-skill\n---\n")
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text(
                "`/real-skill` を使う。namespace 付き `/codex:review` は対象外。\n"
                "パス `/tmp/.flag-file` も対象外。\n",
                encoding="utf-8",
            )

            findings = references.check_prose_skill_references(root)

            self.assertEqual(findings, [])

    def test_allows_bare_absolute_path_reference(self):
        """`/tmp` のような単一セグメント絶対パスは skill 参照と同じ字面になる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extras_skills = root / "packages" / "extras" / "_active" / "skills"
            extras_skills.mkdir(parents=True)
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text(
                "一時ファイルは `/tmp` 直下ではなく `$TMPDIR` に書く。\n"
                "`/usr` や `/var` も同じくパス表記。\n",
                encoding="utf-8",
            )

            findings = references.check_prose_skill_references(root)

            self.assertEqual(findings, [])

    def test_allows_project_local_skill_reference(self):
        """repo 直下 .claude/skills/ の project-local skill は既知名として扱う。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_skill = root / ".claude" / "skills" / "sync-settings"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: sync-settings\n---\n", encoding="utf-8"
            )
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text(
                "配布は `/sync-settings --push` で行う。\n", encoding="utf-8"
            )

            findings = references.check_prose_skill_references(root)

            self.assertEqual(findings, [])


class TestCorePurity(unittest.TestCase):
    def test_detects_blocked_term_in_paths_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('BLOCKED_TERMS=acme-corp,xyzzy\n')
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "bad-rule.md").write_text(
                '---\npaths:\n  - "projects/acme-corp-dashboard/**"\n---\n\nGeneric content.\n'
            )

            findings = skills.check_core_purity(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("acme-corp", findings[0].message)

    def test_detects_blocked_term_in_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('BLOCKED_TERMS=acme-corp,xyzzy\n')
            skill_dir = root / "packages" / "core" / "skills" / "bad-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: bad-skill\n---\n\nacme-corp-dashboard specific.\n"
            )

            findings = skills.check_core_purity(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("acme-corp", findings[0].message)

    def test_passes_clean_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('BLOCKED_TERMS=acme-corp,xyzzy\n')
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "clean-rule.md").write_text(
                "---\ndescription: Generic rule\n---\n\nNo project names here.\n"
            )

            findings = skills.check_core_purity(root)

            self.assertEqual(findings, [])

    def test_no_env_file_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "packages" / "core" / "rules"
            rules.mkdir(parents=True)
            (rules / "some-rule.md").write_text("anything\n")

            findings = skills.check_core_purity(root)

            self.assertEqual(findings, [])


class TestVendoredNotices(unittest.TestCase):
    def test_warns_when_notice_says_do_not_redistribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "vendored-skill", "---\nname: vendored-skill\n---\n")
            (
                root
                / "packages"
                / "core"
                / "skills"
                / "vendored-skill"
                / "NOTICE.txt"
            ).write_text(
                "Source: https://example.com/foo\n"
                "Vendored: 2026-06-11 (no upstream LICENSE — private personal "
                "use only, do not redistribute)\n",
                encoding="utf-8",
            )

            findings = skills.check_vendored_notices(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "warn")
            self.assertIn("vendored-skill", findings[0].message)

    def test_no_findings_when_no_notice_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "plain-skill", "---\nname: plain-skill\n---\n")

            findings = skills.check_vendored_notices(root)

            self.assertEqual(findings, [])

    def test_no_findings_when_notice_has_no_redistribution_restriction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "open-skill", "---\nname: open-skill\n---\n")
            (
                root / "packages" / "core" / "skills" / "open-skill" / "NOTICE.txt"
            ).write_text(
                "Source: https://example.com/bar\nVendored: 2026-07-02\n",
                encoding="utf-8",
            )

            findings = skills.check_vendored_notices(root)

            self.assertEqual(findings, [])


class TestPlansIndex(unittest.TestCase):
    def _make_plans(self, root: Path, index_status: str, fm_status: str) -> None:
        plans = root / "docs" / "plans"
        plans.mkdir(parents=True)
        (plans / "README.md").write_text(
            "| # | Title | Status |\n"
            "| --- | --- | --- |\n"
            f"| 001 | demo-plan | {index_status} |\n",
            encoding="utf-8",
        )
        (plans / "001-demo-plan.md").write_text(
            f"---\nstatus: {fm_status}\n---\n\n# 001\n", encoding="utf-8"
        )

    def test_returns_error_when_index_status_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_plans(root, index_status="in-progress", fm_status="closed")

            findings = plans.check_plans_index(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("001-demo-plan.md", findings[0].message)

    def test_ok_when_index_status_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_plans(root, index_status="closed", fm_status="closed")

            findings = plans.check_plans_index(root)

            self.assertEqual(findings, [])


def _make_target_config(root: Path, name: str, config: dict) -> Path:
    """Write a config.json into packages/targets/{name}/ and return its path."""
    target_dir = root / "packages" / "targets" / name
    target_dir.mkdir(parents=True, exist_ok=True)
    config_path = target_dir / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _write_target_schema(root: Path) -> None:
    """Copy the real schema into the temp repo root."""
    real_schema = REPO_ROOT / "schemas" / "target-config.schema.json"
    schema_dir = root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "target-config.schema.json").write_bytes(real_schema.read_bytes())


class TestConfigSchema(unittest.TestCase):
    def test_valid_config_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_target_schema(root)
            _make_target_config(root, "mytool", {
                "name": "mytool",
                "displayName": "My Tool",
                "configDir": "~/.mytool",
                "configFile": "config.json",
                "instructionsFile": "AGENTS.md",
                "distribute": {
                    "AGENTS.md": {"source": "packages/core/CLAUDE.md"}
                }
            })

            findings = distribution_sources.check_config_schema(root)

            self.assertEqual(findings, [])

    def test_missing_required_field_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_target_schema(root)
            # Missing "name"
            _make_target_config(root, "badtool", {
                "displayName": "Bad Tool",
                "configDir": "~/.badtool",
                "configFile": "config.json",
                "instructionsFile": "AGENTS.md",
                "distribute": {}
            })

            findings = distribution_sources.check_config_schema(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("name", findings[0].message)

    def test_no_schema_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # No schemas/ directory → silently skip
            _make_target_config(root, "mytool", {
                "name": "mytool",
                "displayName": "My Tool",
                "configDir": "~/.mytool",
                "configFile": "config.json",
                "instructionsFile": "AGENTS.md",
                "distribute": {}
            })

            findings = distribution_sources.check_config_schema(root)

            self.assertEqual(findings, [])


def _make_commands_md(root: Path, commands: list[str]) -> None:
    skills_dir = root / "packages" / "core"
    skills_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Commands\n\n"]
    for cmd in commands:
        lines.append(f"`/{cmd}` — description\n\n")
    (skills_dir / "commands.md").write_text("".join(lines), encoding="utf-8")


class TestCheckCommandsVsSkills(unittest.TestCase):
    def test_detects_ghost_command_not_in_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "real-skill", "---\nname: real-skill\n---\n")
            _make_commands_md(root, ["real-skill", "ghost-command"])

            findings = skills.check_commands_vs_skills(root)

            ghost_findings = [f for f in findings if "ghost-command" in f.message]
            self.assertEqual(len(ghost_findings), 1)
            # .gitmodules 宣言なし = extras 未取得と区別できないため error
            self.assertEqual(ghost_findings[0].level, "error")
            self.assertIn("ghost-command", ghost_findings[0].message)

    def test_downgrades_ghost_command_to_warn_when_extras_submodule_uninitialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "real-skill", "---\nname: real-skill\n---\n")
            _make_commands_md(root, ["real-skill", "ghost-command"])
            (root / "packages" / "extras" / "_active").mkdir(parents=True)
            (root / ".gitmodules").write_text(
                '[submodule "packages/extras/_active"]\n'
                "\tpath = packages/extras/_active\n"
                "\turl = git@example.com:x/y.git\n",
                encoding="utf-8",
            )

            findings = skills.check_commands_vs_skills(root)

            ghost_findings = [f for f in findings if "ghost-command" in f.message]
            self.assertEqual(len(ghost_findings), 1)
            self.assertEqual(ghost_findings[0].level, "warn")

    def test_detects_skill_missing_from_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "listed-skill", "---\nname: listed-skill\n---\n")
            _make_skill(root, "unlisted-skill", "---\nname: unlisted-skill\n---\n")
            _make_commands_md(root, ["listed-skill"])

            findings = skills.check_commands_vs_skills(root)

            missing_findings = [f for f in findings if "unlisted-skill" in f.message]
            self.assertEqual(len(missing_findings), 1)
            self.assertEqual(missing_findings[0].level, "warn")

    def test_no_findings_when_commands_and_skills_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "my-skill", "---\nname: my-skill\n---\n")
            _make_commands_md(root, ["my-skill"])

            findings = skills.check_commands_vs_skills(root)

            self.assertEqual(findings, [])


def _make_rule(root: Path, name: str, content: str = "# rule\n") -> None:
    rules_dir = root / "packages" / "core" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / name).write_text(content, encoding="utf-8")


class TestRulesPathReferences(unittest.TestCase):
    def test_returns_error_for_dangling_rules_path_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rule(root, "core-standards.md")
            agents_dir = root / "packages" / "core" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "reviewer.md").write_text(
                "`rules/core-standards.md` と `rules/nonexistent.md` を読む。\n",
                encoding="utf-8",
            )

            findings = references.check_rules_path_references(root)

            self.assertEqual(len(findings), 1)
            # extras 未取得時は warn に格下げ
            self.assertEqual(findings[0].level, "warn")
            self.assertIn("nonexistent.md", findings[0].message)

    def test_detects_dangling_reference_as_error_when_extras_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages" / "extras" / "_active" / "rules").mkdir(parents=True)
            agents_dir = root / "packages" / "core" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "reviewer.md").write_text(
                "`rules/nonexistent.md` を読む。\n", encoding="utf-8"
            )

            findings = references.check_rules_path_references(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("nonexistent.md", findings[0].message)

    def test_allows_existing_rule_and_extras_rule_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rule(root, "core-standards.md")
            (root / "packages" / "extras" / "_active" / "rules").mkdir(parents=True)
            (
                root / "packages" / "extras" / "_active" / "rules" / "project.md"
            ).write_text("# project\n", encoding="utf-8")
            agents_dir = root / "packages" / "core" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "reviewer.md").write_text(
                "`~/.claude/rules/core-standards.md` と `rules/project.md` を読む。\n",
                encoding="utf-8",
            )

            findings = references.check_rules_path_references(root)

            self.assertEqual(findings, [])


class TestSkillFrontmatterReferences(unittest.TestCase):
    def test_returns_error_when_reference_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(
                root,
                "audit-skill",
                "---\nname: audit-skill\nreferences:\n"
                "  - ../../knowledge-notes/missing.md\n---\n\nbody\n",
            )

            findings = skills.check_skill_frontmatter_references(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("missing.md", findings[0].message)

    def test_passes_when_reference_path_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_notes = root / "packages" / "core" / "knowledge-notes"
            knowledge_notes.mkdir(parents=True)
            (knowledge_notes / "present.md").write_text("# present\n", encoding="utf-8")
            _make_skill(
                root,
                "audit-skill",
                "---\nname: audit-skill\nreferences:\n"
                "  - ../../knowledge-notes/present.md\n---\n\nbody\n",
            )

            self.assertEqual(skills.check_skill_frontmatter_references(root), [])

    def test_returns_empty_when_no_references_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_skill(root, "plain-skill", "---\nname: plain-skill\n---\n\nbody\n")

            self.assertEqual(skills.check_skill_frontmatter_references(root), [])


class TestRuntimeAdapterWiring(unittest.TestCase):
    def test_detects_dead_opencode_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            umbrella = root / "packages/runtimes/opencode/harunon.js"
            modules = root / "packages/core/opencode-plugins"
            umbrella.parent.mkdir(parents=True)
            modules.mkdir(parents=True)
            umbrella.write_text(
                'import { A } from "../runtime/harunon-opencode/a.js";\n',
                encoding="utf-8",
            )
            (modules / "a.js").write_text("export const A = 1;\n", encoding="utf-8")
            (modules / "dead.js").write_text("export const Dead = 1;\n", encoding="utf-8")

            findings = distribution_sources.check_runtime_adapter_wiring(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("dead.js", findings[0].message)

    # codex の dispatcher / builder の hook 一覧一致チェックは廃止した。両者が
    # hook-pipeline.json から導出するようになり不一致が構造的に起きないため、
    # 検査は「一覧をハードコードに戻さないこと」へ移した
    # （scripts/tests/test_hook_pipeline.py::test_rehardcoded_codex_hook_list_is_detected）。

    def test_accepts_selective_codex_dispatcher_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "packages/runtimes/codex/harunon-core/scripts/codex_hook.py"
            builder = root / "scripts/build-codex-plugin.py"
            adapter.parent.mkdir(parents=True)
            builder.parent.mkdir(parents=True)
            adapter.write_text('scripts.append("used.sh")\n', encoding="utf-8")
            builder.write_text('CODEX_HOOKS = (\n    "used.sh",\n)\n', encoding="utf-8")

            self.assertEqual(distribution_sources.check_runtime_adapter_wiring(root), [])


class TestRepoIntegration(unittest.TestCase):
    def test_current_repo_passes_meta_checks(self):
        findings = vh.run_checks(REPO_ROOT)
        errors = [f for f in findings if f.level == "error"]
        self.assertEqual(errors, [], msg="\n".join(f.message for f in errors))


class TestSettingsNoDefaultProxyUrl(unittest.TestCase):
    """settings.json に ANTHROPIC_BASE_URL がデフォルトで入っていないことを検証"""

    def test_no_anthropic_base_url_in_core_settings(self):
        settings_path = REPO_ROOT / "packages" / "core" / "settings.json"
        content = settings_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "ANTHROPIC_BASE_URL",
            content,
            "ANTHROPIC_BASE_URL は SSOT に入れない（opt-in はローカルのみ）",
        )

    def test_rtk_rewrite_hook_present_in_settings(self):
        settings_path = REPO_ROOT / "packages" / "core" / "settings.json"
        content = settings_path.read_text(encoding="utf-8")
        self.assertIn(
            "rtk-rewrite.sh",
            content,
            "rtk-rewrite.sh hook が settings.json から消えていない",
        )

    def test_block_grep_hook_present_in_settings(self):
        settings_path = REPO_ROOT / "packages" / "core" / "settings.json"
        content = settings_path.read_text(encoding="utf-8")
        self.assertIn(
            "block-grep-in-bash.sh",
            content,
            "block-grep-in-bash.sh hook が settings.json から消えていない",
        )


if __name__ == "__main__":
    unittest.main()

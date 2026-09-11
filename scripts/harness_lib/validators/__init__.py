"""harness_lib.validators — validate-harness の各 check をモジュール単位で持つ。

各モジュールは `CHECKS: dict[name, fn]` を公開する（check 関数は
`repo_root -> list[Finding]` の純関数）。新しい check を追加するとき編集する
場所はここ 1 箇所だけ: `CHECKS` タプルに `(name, fn)` を 1 行足す。この並びが
そのまま実行順 = 出力順になる（過去の run_checks の手続き列挙順を保持し、
出力の互換性を守るための明示的な並び。check 間に実行順依存はない）。
"""
from __future__ import annotations

from pathlib import Path

from .. import capabilities, danger_rules, hook_pipeline, model_routing
from ..validator_registry import Finding
from .budget import check_always_loaded_budget, check_target_residency_budget
from .context_md import check_context_scale_counts, check_context_target_table
from .dead_symbols import check_dead_symbols
from .model_portability import check as check_model_portability
from .distribution_sources import (
    check_config_schema,
    check_hooks_wiring,
    check_no_symlinks_in_distribution_sources,
    check_runtime_adapter_wiring,
    check_target_config_sources,
)
from .lessons import check_lessons
from .plans import check_plans_index
from .references import check_prose_skill_references, check_rules_path_references
from .skills import (
    check_commands_vs_skills,
    check_core_purity,
    check_skill_frontmatter,
    check_skill_frontmatter_references,
    check_skill_md_casing,
    check_vendored_notices,
)
from .codex_features import check_codex_features
from .workflow_contract import check_core_workflow_contract

CHECKS = (
    ("capability-contract", capabilities.check),
    ("config-schema", check_config_schema),
    ("codex-features", check_codex_features),
    ("danger-rules", danger_rules.check),
    ("hook-pipeline", hook_pipeline.check),
    ("model-routing", model_routing.check),
    ("model-portability", check_model_portability),
    ("core-workflow-contract", check_core_workflow_contract),
    ("runtime-adapter-wiring", check_runtime_adapter_wiring),
    ("target-config-sources", check_target_config_sources),
    ("no-symlinks-in-distribution-sources", check_no_symlinks_in_distribution_sources),
    ("commands-vs-skills", check_commands_vs_skills),
    ("skill-md-casing", check_skill_md_casing),
    ("skill-frontmatter", check_skill_frontmatter),
    ("skill-frontmatter-references", check_skill_frontmatter_references),
    ("hooks-wiring", check_hooks_wiring),
    ("context-scale-counts", check_context_scale_counts),
    ("context-target-table", check_context_target_table),
    ("always-loaded-budget", check_always_loaded_budget),
    ("target-residency-budget", check_target_residency_budget),
    ("prose-skill-references", check_prose_skill_references),
    ("rules-path-references", check_rules_path_references),
    ("core-purity", check_core_purity),
    ("dead-symbols", check_dead_symbols),
    ("vendored-notices", check_vendored_notices),
    ("lessons", check_lessons),
    ("plans-index", check_plans_index),
)


def run_checks(repo_root: Path, *, only: set[str] | None = None) -> list[Finding]:
    """全 (または only で絞られた) check を CHECKS の順で実行して findings を集約."""
    findings: list[Finding] = []
    for name, fn in CHECKS:
        if only is not None and name not in only:
            continue
        findings.extend(fn(repo_root))
    return findings


__all__ = ["CHECKS", "run_checks"]

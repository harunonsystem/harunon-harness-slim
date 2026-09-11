"""CONTEXT.md の管理規模テーブルと「ツール間の差異」表を実体と突合する。"""
from __future__ import annotations

import re
from pathlib import Path

from ..frontmatter import harness_skill_dirs
from ..validator_registry import Finding
from ._common import target_configs


def check_context_target_table(repo_root: Path) -> list[Finding]:
    """CONTEXT.md「ツール間の差異」表の列とpackages/targets/実ディレクトリの一致を検証。

    表の列見出しはツール表示名（例: "Codex Desktop"）で書かれるため、
    ディレクトリ名（例: "codex"）が見出しに部分一致（大小無視・空白無視）
    するかで突合する。
    """
    context_md = repo_root / "CONTEXT.md"
    if not context_md.is_file():
        return []
    content = context_md.read_text(encoding="utf-8")

    match = re.search(r"^\|\s*項目\s*\|(.+)\|\s*$", content, re.MULTILINE)
    if not match:
        return []

    header_cells = [c.strip() for c in match.group(1).split("|") if c.strip()]
    normalized_header = [c.lower().replace(" ", "") for c in header_cells]

    configs, findings = target_configs(repo_root, "context-target-table")
    target_names = [
        config_path.parent.name
        for config_path, config in configs
        if config.get("instructionsFile") != "" and not config.get("auxiliary")
    ]
    if not target_names:
        return findings

    missing = sorted(
        name for name in target_names if not any(name in h for h in normalized_header)
    )
    extra = sorted(
        header_cells[i]
        for i, h in enumerate(normalized_header)
        if not any(name in h for name in target_names)
    )

    if missing:
        findings.append(
            Finding(
                check="context-target-table",
                level="error",
                message=(
                    "CONTEXT.md「ツール間の差異」表に列がないターゲット: "
                    + ", ".join(missing)
                ),
            )
        )
    if extra:
        findings.append(
            Finding(
                check="context-target-table",
                level="error",
                message=(
                    "CONTEXT.md「ツール間の差異」表に packages/targets/ に実在しない列: "
                    + ", ".join(extra)
                ),
            )
        )
    return findings


def scale_actuals(repo_root: Path) -> dict[str, int | None]:
    """CONTEXT.md「管理規模」の core 列に対応する実体の数。

    check_context_scale_counts の照合元であり、public slim の生成（build-public-slim.py）が
    同じ数え方で CONTEXT.md の数字を書き直すためにも使う（数え方を 2 箇所に持たない）。
    """
    return {
        "skills": sum(
            1 for d in harness_skill_dirs(repo_root) if (d / "SKILL.md").is_file()
        ),
        "rules": len(list((repo_root / "packages" / "core" / "rules").glob("*.md")))
        if (repo_root / "packages" / "core" / "rules").is_dir()
        else None,
        "hooks": len(
            [c for c in (repo_root / "packages" / "core" / "hooks").iterdir() if c.is_file()]
        )
        if (repo_root / "packages" / "core" / "hooks").is_dir()
        else None,
        "ADRs": len(list((repo_root / "docs" / "adr").glob("[0-9]*.md")))
        if (repo_root / "docs" / "adr").is_dir()
        else None,
    }


def scale_count_pattern(category: str) -> re.Pattern[str]:
    """管理規模テーブルの `| <category> | <n>` 行。validator と slim 生成が同じ行を見る。"""
    return re.compile(rf"^(\|\s*{category}\s*\|\s*)(\d+)", re.MULTILINE)


def check_context_scale_counts(repo_root: Path) -> list[Finding]:
    """CONTEXT.md の管理規模テーブル（core 列 + ADRs）と実体の一致を検証"""
    context_md = repo_root / "CONTEXT.md"
    if not context_md.is_file():
        return []
    content = context_md.read_text(encoding="utf-8")
    actuals = scale_actuals(repo_root)

    findings: list[Finding] = []
    for category, actual in actuals.items():
        if actual is None:
            continue
        match = scale_count_pattern(category).search(content)
        if not match:
            continue
        documented = int(match.group(2))
        if documented != actual:
            findings.append(
                Finding(
                    check="context-scale-counts",
                    level="error",
                    message=(
                        f"CONTEXT.md の管理規模 {category} が実体と不一致: "
                        f"記載={documented}, 実体={actual}"
                    ),
                )
            )
    return findings


CHECKS = {
    "context-scale-counts": check_context_scale_counts,
    "context-target-table": check_context_target_table,
}

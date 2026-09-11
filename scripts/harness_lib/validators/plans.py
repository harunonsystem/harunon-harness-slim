"""docs/plans の索引 ↔ 各 plan frontmatter の status 一致を検証する。"""
from __future__ import annotations

import re
from pathlib import Path

from ..validator_registry import Finding


def check_plans_index(repo_root: Path) -> list[Finding]:
    """docs/plans/README.md の索引 status ↔ 各 plan の frontmatter status の一致を検証。"""
    plans_dir = repo_root / "docs" / "plans"
    index_md = plans_dir / "README.md"
    if not index_md.is_file():
        return []

    index_statuses: dict[str, str] = {}
    for m in re.finditer(
        r"^\|\s*(\d+)\s*\|\s*[^|]+\|\s*([a-z-]+)\s*\|", index_md.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        index_statuses[m.group(1)] = m.group(2)

    findings: list[Finding] = []
    for plan in sorted(plans_dir.glob("[0-9]*.md")):
        number = plan.name.split("-", 1)[0]
        status_match = re.search(
            r"^status:\s*(\S+)", plan.read_text(encoding="utf-8"), re.MULTILINE
        )
        actual = status_match.group(1) if status_match else None
        documented = index_statuses.get(number)
        if actual is None:
            findings.append(
                Finding(
                    check="plans-index",
                    level="warn",
                    message=f"{plan.relative_to(repo_root)}: frontmatter に status がありません",
                )
            )
            continue
        if documented is None:
            findings.append(
                Finding(
                    check="plans-index",
                    level="warn",
                    message=f"docs/plans/README.md の索引に {plan.name} の行がありません",
                )
            )
            continue
        if documented != actual:
            findings.append(
                Finding(
                    check="plans-index",
                    level="error",
                    message=(
                        f"docs/plans/README.md の status が {plan.name} と不一致: "
                        f"索引={documented}, frontmatter={actual}"
                    ),
                )
            )
    return findings


CHECKS = {"plans-index": check_plans_index}

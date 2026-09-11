"""散文中の `/skill` 参照と `rules/<name>.md` パス参照の実在を検証する。"""
from __future__ import annotations

import re
from pathlib import Path

from ..curated_skills import list_curated_skills
from ..frontmatter import skill_names
from ..validator_registry import Finding

_PROSE_SKILL_REF_RE = re.compile(r"`/([a-z][a-z0-9-]+)`")
_RULES_PATH_REF_RE = re.compile(r"(?:~/\.claude/)?rules/([a-z0-9-]+\.md)")

# backtick 付きの単一セグメント絶対パス（`/tmp` 等）は skill 参照と同じ字面になる。
# CLAUDE.md の sandbox 節のように文書がパスを言及しただけで dangling 扱いされるため、
# POSIX のルート直下ディレクトリ名は参照候補から除外する。
_POSIX_ROOT_DIRS = frozenset(
    {
        "bin",
        "dev",
        "etc",
        "home",
        "mnt",
        "opt",
        "private",
        "proc",
        "root",
        "sbin",
        "srv",
        "sys",
        "tmp",
        "usr",
        "var",
    }
)


def _known_invocable_names(repo_root: Path) -> set[str]:
    """`/name` 参照の解決先として有効な名前の集合（skills + commands）。

    `.claude/skills/`（repo 直下）は harness 運用専用の project-local skill
    （配布されず、この harness リポジトリでの作業時のみ有効）。CLAUDE.md /
    rules からの言及も dangling 扱いにしないよう既知名に含める。

    rulesync が外部から配る skill（curated）も既知名に含める。SSOT に vendored
    コピーを持たず bootstrap Step 2.5 が配るため、lockfile が唯一の宣言元になる。
    """
    names: set[str] = list_curated_skills(repo_root)
    for skills_dir in (
        repo_root / "packages" / "core" / "skills",
        repo_root / "packages" / "extras" / "_active" / "skills",
        repo_root / ".claude" / "skills",
    ):
        names |= skill_names(skills_dir)
    commands_dir = repo_root / "packages" / "core" / "commands"
    if commands_dir.is_dir():
        names |= {p.stem for p in commands_dir.glob("*.md")}
    return names


def check_prose_skill_references(repo_root: Path) -> list[Finding]:
    """rules/*.md と CLAUDE.md 内の `/skill` backtick 参照が実在するかを検証。

    存在しないスキルの起動を毎セッション指示し続ける事故
    （例: 過去の `/figma-sync-tokens` 残留）を防ぐ。
    namespace 付き（`/codex:review` 等）は plugin 由来のため対象外。
    POSIX のルート直下ディレクトリ名（`/tmp` 等）はパス表記として扱い対象外。
    """
    core = repo_root / "packages" / "core"
    scan_targets = sorted((core / "rules").glob("*.md")) if (core / "rules").is_dir() else []
    if (core / "CLAUDE.md").is_file():
        scan_targets.append(core / "CLAUDE.md")
    if not scan_targets:
        return []

    extras_dir = repo_root / "packages" / "extras" / "_active" / "skills"
    extras_available = extras_dir.is_dir()
    known = _known_invocable_names(repo_root)
    findings: list[Finding] = []
    for path in scan_targets:
        content = path.read_text(encoding="utf-8")
        for match in _PROSE_SKILL_REF_RE.finditer(content):
            name = match.group(1)
            if name in known or name in _POSIX_ROOT_DIRS:
                continue
            level = "warn" if not extras_available else "error"
            findings.append(
                Finding(
                    check="prose-skill-references",
                    level=level,
                    message=(
                        f"{path.relative_to(repo_root)}: 存在しないスキル/コマンドへの"
                        f"参照: /{name}"
                        + ("（extras 未取得のため warn）" if not extras_available else "")
                    ),
                )
            )
    return findings


def _rules_path_scan_targets(repo_root: Path) -> list[Path]:
    """`rules/<name>.md` 参照を走査する対象ファイル一覧。"""
    core = repo_root / "packages" / "core"
    targets: list[Path] = []
    agents_dir = core / "agents"
    if agents_dir.is_dir():
        targets.extend(sorted(agents_dir.glob("*.md")))
    skills_dir = core / "skills"
    if skills_dir.is_dir():
        targets.extend(sorted(skills_dir.glob("*/SKILL.md")))
    if (core / "CLAUDE.md").is_file():
        targets.append(core / "CLAUDE.md")
    if (core / "commands.md").is_file():
        targets.append(core / "commands.md")
    return targets


def check_rules_path_references(repo_root: Path) -> list[Finding]:
    """agents/*.md・skills/*/SKILL.md・CLAUDE.md・commands.md 内の
    `rules/<name>.md` パス参照が実在するかを検証する。

    2026-06-22 の rules 統合（coding-policy.md 等 3 ファイル削除）で
    参照元の更新漏れが 10+ 箇所残った再発防止（Plan 001）。
    """
    scan_targets = _rules_path_scan_targets(repo_root)
    if not scan_targets:
        return []

    core_rules_dir = repo_root / "packages" / "core" / "rules"
    extras_rules_dir = repo_root / "packages" / "extras" / "_active" / "rules"
    extras_available = extras_rules_dir.is_dir()

    findings: list[Finding] = []
    for path in scan_targets:
        content = path.read_text(encoding="utf-8")
        for match in _RULES_PATH_REF_RE.finditer(content):
            name = match.group(1)
            if (core_rules_dir / name).is_file():
                continue
            if (extras_rules_dir / name).is_file():
                continue
            level = "warn" if not extras_available else "error"
            findings.append(
                Finding(
                    check="rules-path-references",
                    level=level,
                    message=(
                        f"{path.relative_to(repo_root)}: 存在しない rules パスへの"
                        f"参照: rules/{name}"
                        + ("（extras 未取得のため warn）" if not extras_available else "")
                    ),
                )
            )
    return findings


CHECKS = {
    "prose-skill-references": check_prose_skill_references,
    "rules-path-references": check_rules_path_references,
}

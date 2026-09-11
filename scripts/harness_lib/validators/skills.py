"""packages/core/skills と commands.md・rules の内容契約を検証する。"""
from __future__ import annotations

import re
from pathlib import Path

from ..curated_skills import list_curated_skills
from ..frontmatter import (
    extract_frontmatter_references,
    frontmatter_block,
    harness_skill_dirs,
    harness_skill_names,
    skill_names,
)
from ..validator_registry import Finding
from ._common import is_extras_uninitialized

# Claude Code 組み込みコマンド（skills/ にディレクトリが無いが /command として使える）
BUILTIN_COMMANDS = {"review", "init", "security-review"}


def _extract_commands_from_commands_md(commands_md: Path) -> set[str]:
    content = commands_md.read_text(encoding="utf-8")
    commands: set[str] = set()
    for match in re.finditer(r"`(/[^`]+)`", content):
        command = match.group(1)
        if ":" in command:
            continue
        commands.add(command.lstrip("/"))
    return commands


def check_commands_vs_skills(repo_root: Path) -> list[Finding]:
    commands_md = repo_root / "packages" / "core" / "commands.md"
    skills_dir = repo_root / "packages" / "core" / "skills"
    if not commands_md.is_file() or not skills_dir.is_dir():
        return []

    commands = _extract_commands_from_commands_md(commands_md)
    # core + restricted + extras + curated（rulesync 経由の外部 skill）と組み込みコマンドを known とする
    harness_skills = harness_skill_names(repo_root)
    extras_skills = skill_names(repo_root / "packages" / "extras" / "_active" / "skills")
    curated_skills = list_curated_skills(repo_root)
    all_skills = harness_skills | extras_skills | curated_skills | BUILTIN_COMMANDS
    findings: list[Finding] = []

    # extras-only skills は commands.md に載せない方針のため除外
    missing_in_commands = sorted(harness_skills - commands)
    ghost_in_commands = sorted(commands - all_skills)

    if missing_in_commands:
        findings.append(
            Finding(
                check="commands-vs-skills",
                level="warn",
                message=(
                    "commands.md に未記載のスキル: "
                    + ", ".join(missing_in_commands)
                ),
            )
        )
    if ghost_in_commands:
        # extras submodule 未取得時は「extras 側にしか存在しない skill」の可能性を
        # 否定できないため warning に落とす（check_target_config_sources と同じ扱い）
        extras_uninit = is_extras_uninitialized(repo_root)
        findings.append(
            Finding(
                check="commands-vs-skills",
                level="warn" if extras_uninit else "error",
                message=(
                    "commands.md にあるが skills/ に存在しない: "
                    + ", ".join(ghost_in_commands)
                    + ("（submodule 未取得のため警告扱い）" if extras_uninit else "")
                ),
            )
        )
    return findings


def check_skill_md_casing(repo_root: Path) -> list[Finding]:
    """SKILL.md の大文字小文字を検証（case-insensitive FS では気づけないため）"""
    findings: list[Finding] = []
    for skill in harness_skill_dirs(repo_root):
        for child in skill.iterdir():
            if child.name.lower() == "skill.md" and child.name != "SKILL.md":
                findings.append(
                    Finding(
                        check="skill-md-casing",
                        level="error",
                        message=(
                            f"{skill.name}: {child.name} は SKILL.md に"
                            "リネームしてください（case-sensitive FS で認識されない）"
                        ),
                    )
                )
    return findings


# frontmatter の 1 行スカラー（`key: value`）。値の引用符とブロックスカラーを見分ける。
_FRONTMATTER_SCALAR_RE = re.compile(r"^([\w-]+):[ \t]+(.*)$")
_YAML_VALUE_OPENERS = "\"'[{|>"


def _unquoted_colon_findings(skill_name: str, content: str) -> list[Finding]:
    """引用符なしの値に `: ` を含む frontmatter 行を検出する。

    Claude Code の frontmatter パーサは寛容だが、pi は strict YAML で読むため
    `description: Guidance for X: skills, ...` を nested mapping と解釈して
    skill 全体の読み込みに失敗する（2026-08-30 に writing-for-agents で発生）。
    ここは PyYAML を足さずに、実際に踏んだこの壊れ方だけを検出する。
    """
    findings: list[Finding] = []
    for line in content.split("\n---", 1)[0].splitlines():
        match = _FRONTMATTER_SCALAR_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if value and value[0] not in _YAML_VALUE_OPENERS and ": " in value:
            findings.append(
                Finding(
                    check="skill-frontmatter",
                    level="error",
                    message=(
                        f"{skill_name}: frontmatter の {key} が引用符なしで `: ` を含みます"
                        "（strict YAML の runtime で skill 全体が読み込めなくなるため \" で囲む）"
                    ),
                )
            )
    return findings


def check_skill_frontmatter(repo_root: Path) -> list[Finding]:
    """SKILL.md の frontmatter 存在と name ↔ ディレクトリ名の一致を検証"""
    findings: list[Finding] = []
    for skill in harness_skill_dirs(repo_root):
        skill_md = skill / "SKILL.md"
        if not skill_md.is_file():
            continue
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            findings.append(
                Finding(
                    check="skill-frontmatter",
                    level="error",
                    message=f"{skill.name}: SKILL.md に YAML frontmatter がありません",
                )
            )
            continue
        match = re.search(r"^name:\s*(\S+)\s*$", content.split("\n---", 1)[0], re.MULTILINE)
        if not match:
            findings.append(
                Finding(
                    check="skill-frontmatter",
                    level="error",
                    message=f"{skill.name}: frontmatter に name がありません",
                )
            )
            continue
        findings.extend(_unquoted_colon_findings(skill.name, content))
        name = match.group(1)
        # vendored skill（ckm: prefix）は upstream 追従のため許容
        if name not in (skill.name, f"ckm:{skill.name}"):
            findings.append(
                Finding(
                    check="skill-frontmatter",
                    level="error",
                    message=(
                        f"{skill.name}: frontmatter name '{name}' が"
                        "ディレクトリ名と一致しません"
                    ),
                )
            )
    return findings


def check_skill_frontmatter_references(repo_root: Path) -> list[Finding]:
    """SKILL.md frontmatter の `references:` パスが実在するかを検証。

    パスは SKILL.md からの相対パスとして解決する。1 スキルにつき
    見つからない参照をまとめて 1 件の Finding にする。
    """
    findings: list[Finding] = []
    for skill in harness_skill_dirs(repo_root):
        skill_md = skill / "SKILL.md"
        if not skill_md.is_file():
            continue
        content = skill_md.read_text(encoding="utf-8")
        missing = [
            ref
            for ref in extract_frontmatter_references(content)
            if not (skill_md.parent / ref).resolve().is_file()
        ]
        if missing:
            findings.append(
                Finding(
                    check="skill-frontmatter-references",
                    level="error",
                    message=(
                        f"{skill.name}: frontmatter references: の参照先が"
                        "存在しません: " + ", ".join(missing)
                    ),
                )
            )
    return findings


def check_core_purity(repo_root: Path) -> list[Finding]:
    """core の skills/rules がプロジェクト固有コンテンツを含んでいないか検証。

    CONTEXT.md の分離基準:
    - 特定プロジェクトのパス構造に依存する → extras
    - 特定フレームワークの固有規約に依存する → extras
    """
    core = repo_root / "packages" / "core"
    env_file = repo_root / ".env"

    # .env の CODENAME を extras 判定キーワードに使う
    codename_terms: list[str] = []
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"BLOCKED_TERMS=(.+)", line)
            if m:
                codename_terms = [
                    t.strip() for t in m.group(1).strip('"').split(",") if t.strip()
                ]

    findings: list[Finding] = []
    scan_dirs = []
    if (core / "skills").is_dir():
        scan_dirs.append(core / "skills")
    if (core / "rules").is_dir():
        scan_dirs.append(core / "rules")

    for scan_dir in scan_dirs:
        for md_path in sorted(scan_dir.rglob("*.md")):
            content = md_path.read_text(encoding="utf-8")
            rel = md_path.relative_to(repo_root)

            # Check 1: paths: frontmatter が特定プロジェクトを参照
            fm_match = frontmatter_block(content)
            if fm_match:
                fm = fm_match.group(1)
                paths_match = re.findall(r'^\s*-\s*"([^"]+)"', fm, re.MULTILINE)
                for p in paths_match:
                    for term in codename_terms:
                        if re.search(term, p, re.IGNORECASE):
                            findings.append(
                                Finding(
                                    check="core-purity",
                                    level="error",
                                    message=(
                                        f"{rel}: paths: に固有名 '{term}' を含む"
                                        f"パターン '{p}' → extras に移動すべき"
                                    ),
                                )
                            )

            # Check 2: BLOCKED_TERMS のリテラルが本文に含まれる
            # (pre-commit でも検出されるが、validate でも二重チェック)
            body = content
            if fm_match:
                body = content[fm_match.end() :]
            for term in codename_terms:
                if re.search(term, body, re.IGNORECASE):
                    findings.append(
                        Finding(
                            check="core-purity",
                            level="error",
                            message=(
                                f"{rel}: 本文に固有名 '{term}' を含む → extras に移動すべき"
                            ),
                        )
                    )

    return findings


def check_vendored_notices(repo_root: Path) -> list[Finding]:
    """vendored スキルの NOTICE.txt に再配布禁止の記載があるか警告する。

    OSS 化・公開時にこれらのスキルを除外し忘れないための事前警告
    （`rules/oss-contribution.md` 参照）。error にはせず warning のみ。
    """
    findings: list[Finding] = []
    for skill in harness_skill_dirs(repo_root):
        notice = skill / "NOTICE.txt"
        if not notice.is_file():
            continue
        content = notice.read_text(encoding="utf-8")
        if "do not redistribute" in content.lower():
            findings.append(
                Finding(
                    check="vendored-notices",
                    level="warn",
                    message=(
                        f"{skill.name}: NOTICE.txt に再配布禁止の記載あり"
                        "（OSS 化・公開時は除外すること）"
                    ),
                )
            )
    return findings


CHECKS = {
    "commands-vs-skills": check_commands_vs_skills,
    "skill-md-casing": check_skill_md_casing,
    "skill-frontmatter": check_skill_frontmatter,
    "skill-frontmatter-references": check_skill_frontmatter_references,
    "core-purity": check_core_purity,
    "vendored-notices": check_vendored_notices,
}

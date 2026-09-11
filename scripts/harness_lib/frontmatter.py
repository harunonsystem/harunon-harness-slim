"""harness_lib.frontmatter — SKILL.md frontmatter の変換と読み取り。

変換は sync-codex-skills.py からセマンティクスを移植。読み取り側（frontmatter
ブロック抽出・`paths:` 判定・`references:` 抽出・skill ディレクトリ列挙）は
validate-harness の各 check が共有する。
"""
from __future__ import annotations

import re
from pathlib import Path

# delimiter を含む `---\n...\n---` ブロック全体（group(1) は本文）
FRONTMATTER_BLOCK_RE = re.compile(r"^---\n(.+?)\n---", re.DOTALL)


def frontmatter_block(content: str) -> re.Match | None:
    """先頭の frontmatter ブロックの Match（無ければ None）。"""
    return FRONTMATTER_BLOCK_RE.match(content)


def has_paths_frontmatter(content: str) -> bool:
    """frontmatter に `paths:` キーがあるか（プロジェクトスコープ限定 = 常時注入されない）。"""
    match = frontmatter_block(content)
    if not match:
        return False
    return bool(re.search(r"^paths:\s*$", match.group(1), re.MULTILINE))


def extract_frontmatter_references(content: str) -> list[str]:
    """SKILL.md frontmatter の `references:` ブロックリストを抽出する。

    想定フォーマット（YAML ライブラリは導入しない）:
        references:
          - ../../knowledge-notes/foo.md
          - ../../knowledge-notes/bar.md
    """
    if not content.startswith("---\n"):
        return []
    frontmatter = content.split("\n---", 1)[0]
    match = re.search(
        r"^references:[ \t]*\n((?:^[ \t]*-[ \t]*\S+[ \t]*\n?)+)",
        frontmatter,
        re.MULTILINE,
    )
    if not match:
        return []
    return re.findall(r"^[ \t]*-[ \t]*(\S+)", match.group(1), re.MULTILINE)


SKILL_ROOTS = (
    ("packages", "core", "skills"),
    ("packages", "restricted", "skills"),
)


def harness_skill_dirs(repo_root: Path) -> list[Path]:
    """harness が配布する skill のディレクトリ（SKILL.md の有無は問わない）。

    restricted はライセンス上 public 再配布できない vendored の区画（ADR-002 Update 2026-09-11）
    だが、配布経路は core と同じ（targets の skills source 配列）なので検証対象も同じ集合にする。
    """
    dirs: list[Path] = []
    for parts in SKILL_ROOTS:
        root = repo_root.joinpath(*parts)
        if root.is_dir():
            dirs.extend(child for child in root.iterdir() if child.is_dir())
    return sorted(dirs, key=lambda p: p.name)


def harness_skill_names(repo_root: Path) -> set[str]:
    """harness が配布する skill 名の集合（core + restricted のうち SKILL.md を持つもの）。"""
    return {d.name for d in harness_skill_dirs(repo_root) if (d / "SKILL.md").is_file()}


def skill_names(skills_dir: Path) -> set[str]:
    """skills_dir 直下で SKILL.md を持つディレクトリ名の集合。"""
    if not skills_dir.is_dir():
        return set()
    return {
        child.name
        for child in skills_dir.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    }


def transform_skill_md(text: str, keep: set) -> str:
    """frontmatter から keep 以外の top-level キー（と継続行）を除去する。

    frontmatter がないテキストはそのまま返す。
    """
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    fm_lines = text[4:end].split("\n")
    kept: list[str] = []
    keep_block = False
    for line in fm_lines:
        if line[:1] not in (" ", "\t") and ":" in line:
            keep_block = line.split(":", 1)[0].strip() in keep
        if keep_block:
            kept.append(line)
    return "---\n" + "\n".join(kept) + text[end:]

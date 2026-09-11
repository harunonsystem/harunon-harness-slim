"""rulesync が upstream から配る skill（curated）の宣言を読む。

実体の .rulesync/skills/.curated/ は gitignore 済みで CI には存在しないため、
tracked な rulesync.lock を唯一の宣言元とする（ADR-011）。validate-harness の
既知名チェックと resolver の curated source 完全性検証が同じ集合を見る。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LOCKFILE_NAME = "rulesync.lock"

# rulesync.lock の skill 名は resolver.CURATED_SKILLS_SOURCE の完全性検証で
# .rulesync/skills/.curated/<name> の 1 パス要素として使われる（ADR-011 Update 2026-08-30。
# 旧 bootstrap.sh Step 2.5 の `rm -rf <skills_dir>/<name>` は廃止済み）。`..` や `/` を
# 含む名前が紛れ込むとパス要素として安全でないため、fail-closed で拒否する。
_SAFE_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def list_curated_skills(repo_root: Path) -> set[str]:
    """rulesync.lock に宣言された skill 名の集合。lock が無ければ空。"""
    lock = Path(repo_root) / LOCKFILE_NAME
    if not lock.is_file():
        return set()
    data = json.loads(lock.read_text(encoding="utf-8"))
    names: set[str] = set()
    for source in data.get("sources", {}).values():
        names.update(source.get("skills", {}))
    return names


def invalid_skill_names(names: set[str]) -> list[str]:
    """パス要素として安全でない skill 名を出現順（ソート済み）で返す。

    空リストなら全名が安全。`.` / `..` は正規表現でも先頭文字要件で弾かれるが、
    意図を明示するため個別にも判定する。
    """
    return sorted(
        name
        for name in names
        if name in (".", "..") or not _SAFE_SKILL_NAME_RE.match(name)
    )

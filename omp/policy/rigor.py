"""Casual check for publication gates (push / PR / merge).

Intentionally stricter than hooks/lib/rigor-profile.sh `rigor_profile`, because it lets an
agent publish without human approval: only the target's github.com owner/repo is matched,
path patterns and the machine `defaultProfile` are ignored, and a casual verdict needs an
explicit owner (`harunonsystem/*`, not `*`). Any read or shape problem means rigorous.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path


def _patterns_file() -> Path:
    return Path(os.environ.get("RIGOR_PATTERNS_FILE") or Path.home() / ".claude" / "rigor-patterns.json")


def is_casual_repository(identity: str) -> bool:
    """identity is repo_target.canonical_repository output, e.g. github.com/owner/repo."""
    host, _, name = identity.partition("/")
    if host != "github.com" or name.count("/") != 1:
        return False
    try:
        entries = json.loads(_patterns_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("pattern"), str):
            return False
        pattern = entry["pattern"].lower()
        # Same first-match order as rigor_profile's remote match; path patterns never match owner/repo.
        if fnmatch.fnmatchcase(name, pattern):
            owner = pattern.split("/", 1)[0]
            return (entry.get("profile") == "casual" and pattern.count("/") == 1
                    and bool(owner) and not any(char in owner for char in "*?["))
    return False

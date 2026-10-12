"""Exact local reference snapshots; audit evidence, never native consent."""
from __future__ import annotations

import hashlib
from pathlib import Path


def snapshot(path: str | Path, base: Path) -> dict:
    original = Path(path).expanduser()
    original = original if original.is_absolute() else base / original
    original = original.absolute()
    resolved = original.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {original}")
    data = resolved.read_bytes()
    return {"path": str(original), "resolvedPath": str(resolved),
            "sha256": hashlib.sha256(data).hexdigest()}


def require_current(reference: dict, base: Path) -> None:
    if not isinstance(reference, dict) or set(reference) != {"path", "resolvedPath", "sha256"}:
        raise ValueError("expected exact path/resolvedPath/sha256 reference")
    if not all(isinstance(value, str) and value for value in reference.values()):
        raise ValueError("invalid file reference")
    if snapshot(reference["path"], base) != reference:
        raise ValueError(f"reference changed: {reference['path']}")

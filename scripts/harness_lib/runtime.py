"""Runtime checks shared by Harness command-line entry points."""
from __future__ import annotations

import sys


def require_supported_python() -> None:
    """Fail clearly before imports fail mysteriously on an old system Python."""
    if sys.version_info < (3, 11):
        actual = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(
            f"Harness requires Python 3.11+ (found {actual}). "
            "Run via '\"$(mise which python3)\" ...' from the repository root."
        )

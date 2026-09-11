"""Select a Codex review model and reasoning effort from a diff."""

from __future__ import annotations

def choose_profile(paths: list[str], *, added: int, deleted: int) -> dict[str, str]:
    """Return the standard review profile (always Sol with medium reasoning)."""
    return {"model": "gpt-5.6-sol", "effort": "medium"}

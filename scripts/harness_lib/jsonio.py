"""harness_lib.jsonio — SSOT table / config JSON の安全な読み込み。

validator や distribution が読む JSON はすべて「トップレベルがオブジェクト」の契約を
持つ。`json.loads(...).get(...)` を各所で書くと、壊れた JSON や `null` / 配列の
root で AttributeError / JSONDecodeError の traceback になり、呼び出し側の
`except ValueError` にも掛からない（2026-08-29 Codex 監査 P1）。読み込みと root 型の
検証をここに一本化し、失敗は常に `JsonLoadError`（ValueError）で報告する。
"""
from __future__ import annotations

import json
from pathlib import Path


class JsonLoadError(ValueError):
    """JSON ファイルが読めない・解析できない・root がオブジェクトでない。"""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def load_json_object(path: Path) -> dict:
    """path の JSON を読み、root が dict であることを保証して返す。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise JsonLoadError(path, f"読み込みに失敗しました: {error.strerror or error}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise JsonLoadError(path, f"JSON として解析できません: {error.msg} (line {error.lineno})") from error
    if not isinstance(data, dict):
        raise JsonLoadError(path, f"root はオブジェクトである必要があります: {type(data).__name__}")
    return data


__all__ = ["JsonLoadError", "load_json_object"]

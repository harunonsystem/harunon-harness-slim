"""harness_lib.merge — settings.json への overlay deep merge。

merge-settings.py CLI からセマンティクスを移植。

マージ規則:
- dict 同士は再帰的にマージ
- 配列・スカラーは overlay 側で「置換」する（結合しない）。
  permissions.allow 等のリストを overlay に書くと既存値が丸ごと消えるので注意。
"""
from __future__ import annotations


def deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = v


def merge_overlay_into_settings(settings: dict, overlay: dict, overlay_name: str) -> None:
    """overlay を settings に適用する（in-place）。

    overlay_name が "env.json" の場合は settings.env にのみマージ。
    それ以外は settings 全体に deep merge。
    """
    if overlay_name == "env.json":
        settings.setdefault("env", {}).update(overlay)
    else:
        deep_merge(settings, overlay)

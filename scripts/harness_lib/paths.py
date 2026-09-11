"""harness_lib.paths — 宣言由来のパスが基準ディレクトリ内に閉じていることの検証。

config.json / include ディレクティブ由来のパスは「基準ディレクトリ内の相対パス」で
あることが前提だが、検証が各所にコピーされて厳しさがバラついていた。1 箇所に集約する。

SSOT（repo）から読むパスは文字列検査だけでは足りない。symlink の実体を辿れば基準の外へ
出られるため、必ず実体パスまで確認する（2026-07-26 に include 経路で実測。repo 外の
内容が配布物へ埋め込まれた。base を省略できた頃は settingsSync / distribute の source
が文字列検査だけで通っていた）。
"""
from __future__ import annotations

from pathlib import Path


def relative_name(value: str, label: str) -> str:
    """配布先相対の識別子（ledger entry / obsoleteFiles / configFile）を字面検査する。

    配布先では「SSOT を指す symlink が置かれている」のが正当な状態のことがある
    （内容一致の symlink は push で温存し、実行ビットだけ報告する契約）。そのため
    実体パスの containment は見ず、絶対パス・'..'・空だけを拒否する。symlink 経由で
    配布先の外へ出る entry は ledger cleanup が別途 fail-closed に扱う。
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} が空です")

    normalized = value.replace("\\", "/")
    if normalized in (".", "./"):
        raise ValueError(f"{label} にカレントディレクトリは指定できません: {value!r}")
    if normalized.startswith("/") or Path(value).is_absolute():
        raise ValueError(f"{label} に絶対パスは使えません: {value}")
    if ".." in normalized.split("/"):
        raise ValueError(f"{label} に '..' は使えません: {value}")
    return value


def safe_relative(value: str, label: str, *, base: Path) -> str:
    """`value` が `base` 内に閉じた相対パスであることを検証して返す。

    SSOT 側（repo）から読むパス用。base は必須で、symlink の実体が base の外を
    指す場合も拒否する。base 自体がまだ存在しなくてもよい（resolve は非 strict）。
    """
    relative_name(value, label)
    resolved = (base / value).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ValueError(
            f"{label} が {base} の外を指しています"
            f"（symlink の実体を確認）: {value} -> {resolved}"
        ) from None
    return value

#!/usr/bin/env python3
"""codex の machine-local な config.local.toml に sandbox roots を書く（bootstrap の対話生成用）。

Usage:
    codex-local-config.py LOCAL_CFG WORKTREES_PATH GIT_PATH HOME_PATH

bootstrap.sh が heredoc で TOML を組んでいた頃は、入力パスに `"` / `\\` / 改行が含まれると
壊れた TOML を書いて成功表示まで進んだ（2026-08-29 Codex 監査 P1）。パスは絶対パスかつ
1 行であることを検証し、TOML basic string としてエスケープして追記する。
"""
from __future__ import annotations

import sys
from pathlib import Path

SANDBOX_TABLE = "[sandbox_workspace_write]"


def toml_basic_string(value: str) -> str:
    """TOML basic string（"..."）としてエスケープする。"""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_path(label: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label}: 改行を含むパスは受け付けません")
    if not value.startswith("/"):
        raise ValueError(f"{label}: 絶対パスを指定してください: {value!r}")
    return value


def render_sandbox_block(worktrees: str, git_dir: str, home: str) -> str:
    roots = [
        worktrees,
        git_dir,
        f"{home}/.agents/skills/agmsg/db",
        f"{home}/.agents/skills/agmsg/teams",
    ]
    lines = [
        "# codex の machine-local な sandbox 書き込み許可パス（マシンごとに異なる絶対パス）。",
        "# このファイルは gitignore 済み（コミットされない）。",
        SANDBOX_TABLE,
        "writable_roots = [",
    ]
    lines.extend(f"  {toml_basic_string(root)}," for root in roots)
    lines.append("]")
    return "\n".join(lines) + "\n"


def append_sandbox_block(local_cfg: Path, worktrees: str, git_dir: str, home: str) -> None:
    validate_path("worktrees", worktrees)
    validate_path("git", git_dir)
    validate_path("home", home)
    local_cfg.parent.mkdir(parents=True, exist_ok=True)
    existing = local_cfg.read_text(encoding="utf-8") if local_cfg.is_file() else ""
    prefix = "\n" if existing and not existing.endswith("\n\n") else ""
    if existing and not existing.endswith("\n"):
        prefix = "\n\n"
    local_cfg.write_text(existing + prefix + render_sandbox_block(worktrees, git_dir, home), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        append_sandbox_block(Path(argv[1]), argv[2], argv[3], argv[4])
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

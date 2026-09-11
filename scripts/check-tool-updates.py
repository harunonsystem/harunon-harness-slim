#!/usr/bin/env python3
"""harness が宣言しているツールに新しいバージョンが出ていないか確かめる。

doctor の Step 0 は「入っているか」しか見ないので、pin したまま何ヶ月も古い版を
使い続けても誰も気づかない（2026-09-07 に open-code-review が 1.1.10 のまま
upstream 1.11.5 まで離れていた）。

見るのは harness が宣言したツールだけ。`mise.global.example.toml` の `[tools]` と
repo の `mise.toml` の `[tools]` が宣言で、それ以外（netlify-cli 等のマシン固有
ツール）は harness の責務ではないので問い合わせもしない。

上げるかどうかは判断が要るので（メジャー相当の差は破壊的変更を含む。pi は
pi-codex-conversion 3.0.0 の設定スキーマ変更で追随を見送った前例がある）、
ここは検知して報告するだけにする。

exit code:
  0  宣言ツールはすべて最新
  1  新しいバージョンがある
  2  検査できなかった（mise が無い / 問い合わせ失敗 / 一部が未検査）

2 を 0 と分けるのは、検査が走らなかった状態を「最新」と読み違えないため。
呼び出し側（harness-doctor）は 2 を fatal にはせず warning として扱う。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

EXAMPLE_REL = "mise.global.example.toml"
PROJECT_REL = "mise.toml"

# pi / omp は exact pin で、引き上げは mise run agents:update 経由に限定されている
# （mise.toml のコメント。danger-rules の agent-cli-unpinned-install が mise use /
# npm -g の直叩きを block する）。修正コマンドを出すときはこの契約に従う。
AGENTS_UPDATE_TOOLS = frozenset({
    "npm:@earendil-works/pi-coding-agent",
    "npm:@oh-my-pi/pi-coding-agent",
})


@dataclass(frozen=True)
class Declaration:
    """宣言されたツールと、その宣言元。"""

    tools: frozenset[str]
    source_of: dict[str, str]  # tool -> EXAMPLE_REL | PROJECT_REL


def declared_tools(repo_root: Path) -> Declaration:
    """harness が宣言しているツールと宣言元を返す。

    同じツールが両方にあれば project 側（repo の mise.toml）を宣言元とする。
    修正コマンドの出し分けに宣言元が要るため、名前の集合だけでは足りない。
    """
    source_of: dict[str, str] = {}
    for rel in (EXAMPLE_REL, PROJECT_REL):
        path = repo_root / rel
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            for name in tomllib.load(stream).get("tools", {}):
                source_of[name] = rel
    return Declaration(tools=frozenset(source_of), source_of=source_of)


def query_outdated(mise_bin: str, cwd: Path, tools: list[str]) -> dict[str, dict]:
    """宣言ツールだけを対象に `mise outdated --bump --json` を実行する。

    対象を渡さないと global / local の全エントリを問い合わせるため、harness と無関係な
    ツールの遅い backend が timeout を食い潰し、宣言ツールの結果ごと失われる。
    --bump を付けないと pin した range の中しか見ず、range 外の新版（まさに気づきたい
    もの）が "All tools are up to date" に隠れる。
    """
    proc = subprocess.run(
        [mise_bin, "outdated", "--bump", "--json", *tools],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"exit {proc.returncode}")
    return json.loads(proc.stdout or "{}")


def updater_for(tool: str, source: str) -> str:
    """そのツールの宣言元に効く引き上げ方を返す。

    宣言元と違う層を編集するコマンドを出すと、実行しても警告が消えない
    （project の mise.toml が pin しているのに --global を触る等）。
    """
    if tool in AGENTS_UPDATE_TOOLS:
        return f"mise run agents:update -- {tool.rsplit('/', 1)[-1].split('-')[0]} <version>"
    if source == PROJECT_REL:
        return f"{PROJECT_REL} の [tools] を編集して mise install"
    return f"mise use --global --pin {tool}@<version>"


def updates(declaration: Declaration, reported: dict[str, dict]) -> list[str]:
    """宣言済みツールのうち新版があるものを、宣言元に合う直し方付きで返す。"""
    lines: list[str] = []
    for name in sorted(declaration.tools & set(reported)):
        entry = reported[name]
        current = entry.get("current") or entry.get("requested") or "?"
        latest = entry.get("latest") or entry.get("bump") or "?"
        if current == latest:
            continue
        how = updater_for(name, declaration.source_of[name])
        lines.append(f"{name}: {current} → {latest}（{how}）")
    return lines


def unchecked(declaration: Declaration, reported: dict[str, dict], installed: set[str]) -> list[str]:
    """宣言されているのに検査結果が得られなかったツール。

    `mise outdated` は active なツールしか返さないので、未インストールや解決失敗は
    結果に現れない。これを黙って「最新」に含めると、未検査を健全と report してしまう。
    """
    return sorted(declaration.tools - set(reported) - installed)


def installed_tools(mise_bin: str, cwd: Path) -> set[str]:
    """実機に入っているツール名（未インストールと検査失敗を区別するため）。"""
    proc = subprocess.run(
        [mise_bin, "ls", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )
    if proc.returncode != 0:
        return set()
    try:
        return set(json.loads(proc.stdout or "{}"))
    except json.JSONDecodeError:
        return set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    mise_bin = shutil.which("mise")
    if mise_bin is None:
        print("mise が無いためツール更新を確認できませんでした")
        return 2

    declaration = declared_tools(args.repo_root)
    if not declaration.tools:
        print("宣言されたツールがありません")
        return 2

    try:
        reported = query_outdated(mise_bin, args.repo_root, sorted(declaration.tools))
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"ツール更新を確認できませんでした: {error}")
        return 2

    found = updates(declaration, reported)
    skipped = unchecked(declaration, reported, installed_tools(mise_bin, args.repo_root))

    for line in found:
        print(f"新しいバージョン: {line}")
    for name in skipped:
        print(f"未検査（未インストールか解決失敗）: {name}")

    if found and skipped:
        print(f"{len(found)} 件に新版、{len(skipped)} 件が未検査です")
        return 2
    if found:
        print(f"{len(found)} 件のツールに新しいバージョンがあります")
        return 1
    if skipped:
        print(f"{len(skipped)} 件を検査できなかったため、最新かどうか判断できません")
        return 2

    print(f"宣言ツールはすべて最新（{len(declaration.tools)} 件を確認）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""packages/targets/codex/features.json の実測値が、いま入っている codex CLI と合うか確かめる。

features.json は「codex の default はこうだった」という実測のスナップショット。codex が
更新されると静かに古くなるが、validator は table と config.toml の整合しか見ない（CI に
codex CLI が無いため）。ここが唯一の陳腐化検知点になる。

`codex features list` は live の config を読み込んだ実効値を返すので、必ず空の CODEX_HOME
で実行する（そうしないと「宣言したから true」を default と読み違える）。

exit code:
  0  宣言と実測が一致した
  1  ずれを検出した
  2  検査できなかった（codex CLI が無い / features list が失敗した）

2 を 0 と分けるのは、唯一の陳腐化チェックが動かなかった状態を「一致」と読み違えないため。
呼び出し側（harness-doctor）は 2 を fatal にはせず warning として扱う。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TABLE_REL = "packages/targets/codex/features.json"


def measured_features(codex_bin: str) -> dict[str, tuple[str, bool]]:
    """空の CODEX_HOME で `codex features list` を実行し {name: (stage, default)} を返す。

    出力は "<name> <stage...> <true|false>" の空白区切り。stage は "under development" の
    ように空白を含むため、両端から取る。
    """
    with tempfile.TemporaryDirectory() as empty_home:
        proc = subprocess.run(
            [codex_bin, "features", "list"],
            capture_output=True,
            text=True,
            timeout=60,
            env={"CODEX_HOME": empty_home, "PATH": os.environ.get("PATH", "")},
        )
    if proc.returncode != 0:
        raise RuntimeError(f"codex features list が失敗しました: {proc.stderr.strip()}")

    measured: dict[str, tuple[str, bool]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[-1] not in ("true", "false"):
            continue
        measured[parts[0]] = (" ".join(parts[1:-1]), parts[-1] == "true")
    if not measured:
        raise RuntimeError("codex features list の出力を解釈できませんでした")
    return measured


def drifts(table: dict, measured: dict[str, tuple[str, bool]]) -> list[str]:
    """features.json に宣言済みのフラグについて、実測とのずれを人が読める行にして返す。

    codex は 120 以上の feature を持つが、features.json は harness が意見を持つものだけの
    table。実測にあって宣言に無いフラグは「まだ意見が無い」であってずれではないので見ない
    （config.toml に書いたのに宣言が無いケースは validator の codex-features が捕まえる）。
    """
    found: list[str] = []
    for name, entry in table["features"].items():
        if name not in measured:
            if entry["stage"] != "absent":
                found.append(
                    f"{name}: 宣言は stage {entry['stage']} ですが、いまの codex に存在しません"
                    "（stage を absent にするか宣言ごと外してください）"
                )
            continue
        stage, default = measured[name]
        if entry["stage"] == "absent":
            found.append(f"{name}: 宣言は absent ですが、いまの codex には stage {stage} で存在します")
            continue
        if entry["stage"] != stage:
            found.append(f"{name}: stage が宣言 {entry['stage']} → 実測 {stage} に変わりました")
        if entry["default"] != default:
            found.append(
                f"{name}: default が宣言 {entry['default']} → 実測 {default} に変わりました"
                + ("（宣言する意味が無くなった可能性があります）" if entry["declare"] and default else "")
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    codex_bin = shutil.which("codex")
    if codex_bin is None:
        print("codex CLI が無いため features.json の実測突き合わせができませんでした")
        return 2

    table_path = args.repo_root / TABLE_REL
    table = json.loads(table_path.read_text(encoding="utf-8"))

    try:
        measured = measured_features(codex_bin)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"features.json の実測突き合わせを実行できませんでした: {error}")
        return 2

    found = drifts(table, measured)
    if not found:
        print(f"codex features: {table['measuredWith']} の実測と一致（{len(table['features'])} 件）")
        return 0

    print(f"codex features.json が実測とずれています（宣言は {table['measuredWith']} 時点）:")
    for line in found:
        print(f"  - {line}")
    print(f"  → 実測し直して {TABLE_REL} の default / stage / measuredWith / measuredAt を更新してください")
    return 1


if __name__ == "__main__":
    sys.exit(main())

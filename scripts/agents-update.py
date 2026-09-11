#!/usr/bin/env python3
"""mise で exact pin している agent CLI（pi / omp）の版確認と引き上げ。

pin 運用（targets/pi/config.json の前提）のため `mise outdated` / `mise up` は
これらを対象にしない。ここが唯一の引き上げ経路:

  mise run agents:outdated              # pin と npm latest を並べる（読み取りのみ）
  mise run agents:update -- pi 0.84.3   # pin 更新 → mise install → 検証 → 失敗なら pin を戻す

検証は pi なら pi-doctor.py + pi-regression.py、omp なら --version、共通で
bootstrap.sh --check（harness 配布物の drift）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MISE_GLOBAL = Path(os.environ.get("MISE_GLOBAL_CONFIG", Path.home() / ".config/mise/config.toml"))

TOOLS = {
    "pi": "@earendil-works/pi-coding-agent",
    "omp": "@oh-my-pi/pi-coding-agent",
}


def _mise_key(pkg: str) -> str:
    return f'"npm:{pkg}"'


def _pin_pattern(pkg: str) -> re.Pattern[str]:
    return re.compile(rf'^({re.escape(_mise_key(pkg))}\s*=\s*)"([^"]+)"', re.M)


def current_pin(text: str, pkg: str) -> str:
    m = _pin_pattern(pkg).search(text)
    if not m:
        raise SystemExit(f"{MISE_GLOBAL} に {_mise_key(pkg)} の pin 行が無い")
    return m.group(2)


def npm_latest(pkg: str) -> str:
    with urllib.request.urlopen(f"https://registry.npmjs.org/{pkg}/latest", timeout=15) as r:
        return json.load(r)["version"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, **kw)


def cmd_outdated(_: argparse.Namespace) -> int:
    text = MISE_GLOBAL.read_text()
    stale = 0
    print(f"{'tool':<5} {'pin':<10} {'latest':<10}")
    for name, pkg in TOOLS.items():
        pin, latest = current_pin(text, pkg), npm_latest(pkg)
        mark = "" if pin == latest else "  ← mise run agents:update -- " f"{name} {latest}"
        stale += pin != latest
        print(f"{name:<5} {pin:<10} {latest:<10}{mark}")
    return 0


def verify(name: str) -> bool:
    # `mise run` は task 開始時点の config で PATH を組むので、pin 変更後の実体は
    # `mise exec --` で再解決させないと doctor が旧版を掴んで失敗する。
    via_mise = ["mise", "exec", "--"]
    checks = {
        "pi": [
            via_mise + ["python3", str(REPO_ROOT / "scripts/pi-doctor.py")],
            via_mise + ["python3", str(REPO_ROOT / "scripts/pi-regression.py")],
        ],
        "omp": [via_mise + ["omp", "--version"]],
    }[name]
    checks.append([str(REPO_ROOT / "scripts/bootstrap.sh"), "--check"])
    return all(run(c).returncode == 0 for c in checks)


def cmd_update(ns: argparse.Namespace) -> int:
    pkg = TOOLS[ns.tool]
    version = ns.version or npm_latest(pkg)
    text = MISE_GLOBAL.read_text()
    before = current_pin(text, pkg)
    if before == version:
        print(f"{ns.tool} は既に {version}")
        return 0
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version):
        raise SystemExit(f"exact version を指定する（'latest' や range は pin 運用に反する）: {version}")

    def write_pin(v: str) -> None:
        MISE_GLOBAL.write_text(_pin_pattern(pkg).sub(rf'\1"{v}"', text, count=1))

    print(f"{ns.tool}: {before} → {version}")
    write_pin(version)
    ok = run(["mise", "install", f"npm:{pkg}@{version}"]).returncode == 0 and verify(ns.tool)
    if not ok:
        write_pin(before)
        run(["mise", "install", f"npm:{pkg}@{before}"])
        print(f"検証に失敗したので pin を {before} に戻した", file=sys.stderr)
        return 1
    print(f"{ns.tool} {version} に更新し検証を通過。mise.global.example.toml の例も揃えるなら手で更新する")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("outdated").set_defaults(fn=cmd_outdated)
    u = sub.add_parser("update")
    u.add_argument("tool", choices=sorted(TOOLS))
    u.add_argument("version", nargs="?", help="省略時は npm latest")
    u.set_defaults(fn=cmd_update)
    ns = p.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())

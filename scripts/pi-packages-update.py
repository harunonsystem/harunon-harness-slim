#!/usr/bin/env python3
"""pi 拡張（targets/pi/settings.json の packages）の pin 更新。

pi の "packages" は npm / git を exact pin で運用している（pi-doctor.py が
非pinを検出して落とす契約）。scripts/agents-update.py が pi/omp 本体の pin を
担うのと同じ発想で、拡張パッケージ側にも読み取り専用の outdated と、検証込みの
update 経路を用意する:

  mise run pi-packages:outdated              # pin と npm latest / git HEAD を並べる
  mise run pi-packages:update                # stale な全 package を latest に引き上げ
  mise run pi-packages:update -- pi-lens     # 指定した package だけ引き上げ

settings.json は json.dump し直さずテキスト行単位で書き換える（キー順序・タブ
インデントを壊さないため）。検証は validate-harness.py（合否判定）と
bootstrap.sh --check --targets pi（drift の参考表示。pin bump 直後は live との
drift で非0 exitになるのが正常系なので、これ単体では失敗にしない）。

SoL-Pi は pi-subagents の excludedExtensionPackages が settings.json の package
source 文字列と完全一致する必要があるため、git SHA を更新するときは
packages/targets/pi/subagents.json の exclusion も同じ transaction で更新する。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "packages/targets/pi/settings.json"
SUBAGENTS_SETTINGS_PATH = REPO_ROOT / "packages/targets/pi/subagents.json"
SOL_PI_GIT_NAME = "github.com/NVlabs/SoL-Pi"

PIN_LINE = re.compile(r'^\t\t"((?:npm|git):[^"]+)"')
NPM_EXACT = re.compile(r"^npm:((?:@[^/@]+/)?[^@/]+)@(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)$")
GIT_EXACT = re.compile(r"^git:([^@]+)@([0-9a-fA-F]{40})$")


@dataclass(frozen=True)
class Package:
    kind: str  # "npm" | "git"
    name: str  # scoped/unscoped npm name、または "host/owner/repo"
    version: str  # exact semver、または 40桁hex sha
    line_no: int  # settings.json 内の1-based行番号


def parse_spec(spec: str) -> tuple[str, str, str]:
    """`npm:<name>@<exact semver>` / `git:<host>/<path>@<40hex sha>` のみ許可する。"""
    m = NPM_EXACT.match(spec)
    if m:
        return "npm", m.group(1), m.group(2)
    m = GIT_EXACT.match(spec)
    if m:
        return "git", m.group(1), m.group(2)
    raise ValueError(
        f"exact pin ではない（npm:<name>@<semver> / git:<host>/<path>@<40hex sha> のみ許可）: {spec!r}"
    )


def load_packages(text: str) -> list[Package]:
    packages: list[Package] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = PIN_LINE.match(line)
        if not m:
            continue
        kind, name, version = parse_spec(m.group(1))
        packages.append(Package(kind=kind, name=name, version=version, line_no=i))
    return packages


def npm_latest(name: str) -> str:
    # quote の safe を "@" にすると '/' だけが %2F にエンコードされ、scoped 名の
    # 先頭 '@' は literal のまま残る（registry.npmjs.org の期待する形）。
    encoded = urllib.parse.quote(name, safe="@")
    with urllib.request.urlopen(f"https://registry.npmjs.org/{encoded}/latest", timeout=15) as r:
        return json.load(r)["version"]


def git_latest(host_path: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", f"https://{host_path}", "HEAD"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"git ls-remote 失敗: {host_path}\n{result.stderr.strip()}")
    return result.stdout.split()[0]


def latest_of(pkg: Package) -> str:
    return npm_latest(pkg.name) if pkg.kind == "npm" else git_latest(pkg.name)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, **kw)


def cmd_outdated(_: argparse.Namespace) -> int:
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    packages = load_packages(text)
    stale = 0
    print(f"{'name':<45} {'pin':<14} {'latest':<14}")
    for pkg in packages:
        try:
            latest = latest_of(pkg)
        except Exception as e:  # noqa: BLE001 - network/subprocess の失敗を1行で報告して次へ
            print(f"{pkg.name:<45} {pkg.version:<14} ERROR: {e}")
            continue
        is_stale = latest != pkg.version
        stale += is_stale
        pin_disp = pkg.version if pkg.kind == "npm" else pkg.version[:12]
        latest_disp = latest if pkg.kind == "npm" else latest[:12]
        mark = "  ← stale" if is_stale else ""
        print(f"{pkg.name:<45} {pin_disp:<14} {latest_disp:<14}{mark}")
    print(f"{stale} stale")
    return 0


def verify() -> bool:
    validate_rc = run([sys.executable, str(REPO_ROOT / "scripts/validate-harness.py")]).returncode
    bootstrap_rc = run(
        [str(REPO_ROOT / "scripts/bootstrap.sh"), "--check", "--targets", "pi", "--skip-submodule"]
    ).returncode
    print(
        f"(参考) bootstrap --check exit={bootstrap_rc}"
        "（pin bump 直後は live 側がまだ旧 pin なので非0 exitが正常系。合否判定には使わない）"
    )
    return validate_rc == 0


def cmd_update(ns: argparse.Namespace) -> int:
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    packages = load_packages(text)
    subagents_text = (
        SUBAGENTS_SETTINGS_PATH.read_text(encoding="utf-8")
        if SUBAGENTS_SETTINGS_PATH.exists()
        else None
    )

    if ns.names:
        wanted = set(ns.names)
        known = {pkg.name for pkg in packages}
        unknown = wanted - known
        if unknown:
            raise SystemExit(f"settings.json に無い package 名: {', '.join(sorted(unknown))}")
        targets = [pkg for pkg in packages if pkg.name in wanted]
    else:
        targets = packages

    lines = text.splitlines(keepends=True)
    bumps: list[tuple[Package, str]] = []
    new_subagents_text = subagents_text
    for pkg in targets:
        try:
            latest = latest_of(pkg)
        except Exception as e:  # noqa: BLE001 - 1 package の取得失敗で全体を止めない
            print(f"WARN: {pkg.name} の latest 取得に失敗: {e}", file=sys.stderr)
            continue
        if latest == pkg.version:
            continue
        old_spec = f"{pkg.kind}:{pkg.name}@{pkg.version}"
        new_spec = f"{pkg.kind}:{pkg.name}@{latest}"
        parse_spec(new_spec)  # 書き込む値が exact pin 形式か再確認する

        old_line = lines[pkg.line_no - 1]
        new_line = old_line.replace(f"@{pkg.version}\"", f'@{latest}"', 1)
        if new_line == old_line:
            raise SystemExit(f"内部エラー: {pkg.name} の pin 置換に失敗（行 {pkg.line_no}）")
        lines[pkg.line_no - 1] = new_line

        if pkg.kind == "git" and pkg.name == SOL_PI_GIT_NAME:
            if new_subagents_text is None:
                raise SystemExit("SoL-Pi pin 更新には packages/targets/pi/subagents.json が必要")
            if old_spec not in new_subagents_text:
                raise SystemExit(
                    "SoL-Pi の旧 package source が subagents.json の excludedExtensionPackages に無い: "
                    f"{old_spec}"
                )
            new_subagents_text = new_subagents_text.replace(old_spec, new_spec, 1)

        bumps.append((pkg, latest))

    if not bumps:
        print("更新対象なし（既に最新、または対象が見つからなかった）")
        return 0

    new_text = "".join(lines)
    SETTINGS_PATH.write_text(new_text, encoding="utf-8")
    if new_subagents_text is not None and new_subagents_text != subagents_text:
        SUBAGENTS_SETTINGS_PATH.write_text(new_subagents_text, encoding="utf-8")
    print("pin を更新:")
    for pkg, latest in bumps:
        print(f"  {pkg.kind}:{pkg.name}  {pkg.version} → {latest}")

    if not verify():
        SETTINGS_PATH.write_text(text, encoding="utf-8")
        if subagents_text is not None and new_subagents_text != subagents_text:
            SUBAGENTS_SETTINGS_PATH.write_text(subagents_text, encoding="utf-8")
        print("検証(validate-harness.py)に失敗したので pin を元に戻した", file=sys.stderr)
        return 1

    print(
        "検証を通過。反映するには: ./scripts/bootstrap.sh --targets pi\n"
        "その後 pi を再起動して package をインストールさせる"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("outdated").set_defaults(fn=cmd_outdated)
    u = sub.add_parser("update")
    u.add_argument("names", nargs="*", help="省略時は stale な全 package を更新")
    u.set_defaults(fn=cmd_update)
    ns = p.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())

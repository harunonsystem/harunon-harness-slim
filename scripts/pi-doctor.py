#!/usr/bin/env python3
"""Pi の実行経路と設定を、秘密情報を表示せずに診断する。

このスクリプトはライブ設定を変更しない。Pi 本体のインストール経路と、
Pi が読む設定の整合性だけを確認する。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


PACKAGE_NAME = "npm:@earendil-works/pi-coding-agent"
PINNED_NPM = re.compile(r"^npm:(?:@[^/]+/)?[^@/]+@[^@/]+$")
PINNED_GIT = re.compile(r"^git:.+@[^@/]+$")
PINNED_URL = re.compile(r"^(?:https?|ssh|git)://.+@[^/@?#]+$")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _first_line(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return ""
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")


def _pinned_package(spec: object) -> bool:
    if not isinstance(spec, str):
        return False
    if PINNED_NPM.fullmatch(spec) or PINNED_GIT.fullmatch(spec):
        return True
    return bool(PINNED_URL.fullmatch(spec))


def _skill_names(root: Path, *, include_root_files: bool) -> set[str]:
    if not root.is_dir():
        return set()
    names: set[str] = set()
    if include_root_files:
        names.update(path.stem for path in root.glob("*.md"))
    for path in root.rglob("SKILL.md"):
        if path.is_file():
            names.add(path.parent.name)
    return names


def _add_skill_collision_check(
    checks: list[Check], agent_dir: Path, home: Path
) -> None:
    pi_skills = _skill_names(agent_dir / "skills", include_root_files=True)
    shared_skills = _skill_names(home / ".agents" / "skills", include_root_files=False)
    collisions = sorted(pi_skills & shared_skills)
    if collisions:
        checks.append(
            Check(
                "skill-collision",
                "warn",
                f"同名skillが {len(collisions)} 件あります。配布先を一本化してください",
            )
        )
    else:
        checks.append(Check("skill-collision", "ok", "重複なし"))


def collect_checks(agent_dir: Path, timeout: float = 10.0) -> tuple[Path | None, list[Check]]:
    checks: list[Check] = []
    pi_path_text = shutil.which("pi")
    pi_path = Path(pi_path_text).expanduser() if pi_path_text else None
    if pi_path is None:
        checks.append(Check("pi-command", "fail", "PATH上に pi がありません"))
    else:
        version = _first_line(_run([str(pi_path), "--version"], timeout))
        if version:
            checks.append(Check("pi-command", "ok", f"{pi_path} ({version})"))
        else:
            checks.append(Check("pi-command", "fail", f"{pi_path} --version に失敗しました"))

    mise_path_text = shutil.which("mise")
    if mise_path_text is None:
        checks.append(Check("mise-command", "fail", "PATH上に mise がありません"))
    else:
        mise_path = Path(mise_path_text).expanduser()
        mise_ls = _run([str(mise_path), "ls", PACKAGE_NAME], timeout)
        if mise_ls is not None and mise_ls.returncode == 0 and _first_line(mise_ls):
            checks.append(Check("mise-record", "ok", "Pi package の管理記録あり"))
        else:
            checks.append(Check("mise-record", "fail", "miseにPi packageの管理記録がありません"))

        mise_which = _run([str(mise_path), "which", "pi"], timeout)
        mise_pi = _first_line(mise_which)
        if mise_which is None or mise_which.returncode != 0 or not mise_pi:
            checks.append(Check("mise-resolution", "fail", "mise which pi に失敗しました"))
        elif pi_path is None:
            checks.append(Check("mise-resolution", "warn", f"miseの解決先: {mise_pi}"))
        elif os.path.realpath(mise_pi) != os.path.realpath(str(pi_path)):
            checks.append(
                Check(
                    "mise-resolution",
                    "fail",
                    "miseの解決先とPATH上のpi実体が一致しません",
                )
            )
        else:
            checks.append(Check("mise-resolution", "ok", "miseの解決先とPATH上の実体が一致"))

    settings_path = agent_dir / "settings.json"
    if not settings_path.is_file():
        checks.append(Check("settings", "warn", f"settings.jsonがありません: {settings_path}"))
        settings: dict[str, object] = {}
    else:
        try:
            parsed = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            checks.append(Check("settings", "fail", f"settings.jsonを読めません: {settings_path}"))
            settings = {}
        else:
            if isinstance(parsed, dict):
                settings = parsed
                checks.append(Check("settings", "ok", f"settings.json valid: {settings_path}"))
            else:
                settings = {}
                checks.append(Check("settings", "fail", "settings.jsonのトップレベルがobjectではありません"))

    packages = settings.get("packages")
    if packages is None:
        checks.append(Check("package-pins", "warn", "settings.jsonにpackagesがありません"))
    elif not isinstance(packages, list):
        checks.append(Check("package-pins", "fail", "settings.jsonのpackagesが配列ではありません"))
    else:
        unpinned = sum(1 for package in packages if not _pinned_package(package))
        if unpinned:
            checks.append(Check("package-pins", "fail", f"pinされていないpackageが {unpinned} 件あります"))
        else:
            checks.append(Check("package-pins", "ok", f"{len(packages)} packageを検査、全てpin済み"))

    auth_path = agent_dir / "auth.json"
    if auth_path.is_file():
        checks.append(Check("auth-file", "ok", "credential file present（内容は未読）"))
    else:
        checks.append(Check("auth-file", "warn", "credential fileなし（live provider availabilityは未確認）"))

    _add_skill_collision_check(checks, agent_dir, Path.home())
    return pi_path, checks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-dir",
        type=Path,
        default=None,
        help="Pi agent directory（既定: $HOME/.pi/agent）",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="各CLIのtimeout秒")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    agent_dir = (args.agent_dir or Path.home() / ".pi" / "agent").expanduser().resolve()
    pi_path, checks = collect_checks(agent_dir, timeout=max(args.timeout, 0.1))
    failures = sum(check.status == "fail" for check in checks)
    warnings = sum(check.status == "warn" for check in checks)

    if args.json:
        payload = {
            "agent_dir": str(agent_dir),
            "pi_path": str(pi_path) if pi_path else None,
            "checks": [asdict(check) for check in checks],
            "summary": {"failures": failures, "warnings": warnings},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Pi doctor: {agent_dir}")
        for check in checks:
            marker = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}[check.status]
            print(f"[{marker}] {check.name}: {check.detail}")
        print(f"Summary: {failures} failure(s), {warnings} warning(s)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

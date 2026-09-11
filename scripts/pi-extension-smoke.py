#!/usr/bin/env python3
"""Pi の pinned extension 構成を provider なしで実起動する。

対象 package と target 配布の FFF mode extension / pi-tool-display の配布設定を一時的な agent directory に用意し、target default と
PI_FFF_MODE の tools-and-ui / override をそれぞれ RPC 起動する。LLM 呼び出しは
行わないが、extension のロードと tool 名の衝突は実際の Pi で検査する。
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
from typing import Sequence


MODES = ("tools-and-ui", "override")
REQUIRED_PACKAGES = (
    ("pi-fff", "npm:@ff-labs/pi-fff@"),
    ("pi-tool-display", "npm:pi-tool-display@"),
)
CONFIG_PATH = Path("extensions/pi-tool-display/config.json")
FFF_MODE_EXTENSION_PATH = Path("extensions/harness-fff-mode.js")
SMOKE_MODE_OBSERVER_PACKAGE = Path("smoke-mode-observer")
SMOKE_MODE_MARKER = "SMOKE_PI_FFF_MODE="


class SmokeError(RuntimeError):
    """スモーク検査で期待した状態を満たせなかった。"""


def _run(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(argv),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _output(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "process did not start or timed out"
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return output[-4000:] or "(no output)"


def _require_success(result: subprocess.CompletedProcess[str] | None, label: str) -> None:
    if result is None:
        raise SmokeError(f"{label}: process did not start or timed out")
    if result.returncode != 0:
        raise SmokeError(f"{label}: exit={result.returncode}\n{_output(result)}")


def _target_package_specs(repo_root: Path) -> tuple[str, ...]:
    settings_path = repo_root / "packages" / "targets" / "pi" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeError(f"target settingsを読めません: {settings_path}: {error}") from error

    packages = settings.get("packages") if isinstance(settings, dict) else None
    if not isinstance(packages, list):
        raise SmokeError(f"target settingsにpackages配列がありません: {settings_path}")

    specs: list[str] = []
    for label, prefix in REQUIRED_PACKAGES:
        matches = [
            package
            for package in packages
            if isinstance(package, str) and package.startswith(prefix)
        ]
        if len(matches) != 1:
            raise SmokeError(
                f"{label} package pinは1件必要です（検出: {len(matches)}件）"
            )
        specs.append(matches[0])
    return tuple(specs)


def _prepare_agent_dir(repo_root: Path, agent_dir: Path, timeout: float) -> None:
    agent_dir.mkdir(parents=True)
    result = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "distribute.py"),
            "pi",
            "--push",
            "--dest",
            str(agent_dir),
        ],
        cwd=repo_root,
        timeout=timeout,
        env=os.environ.copy(),
    )
    _require_success(result, "pi target distribution")

    distributed_config = agent_dir / CONFIG_PATH
    distributed_mode_extension = agent_dir / FFF_MODE_EXTENSION_PATH
    try:
        config = distributed_config.read_bytes()
        mode_extension = distributed_mode_extension.read_bytes()
    except OSError as error:
        raise SmokeError(
            f"配布済みpi-tool-display設定またはFFF mode extensionがありません: "
            f"{distributed_config}, {distributed_mode_extension}"
        ) from error

    # ターゲットの core extensions は別の依存関係を持つため、tool ownership に
    # 関係する package extensions と、配布された設定だけを残して検査を絞る。
    extensions_dir = agent_dir / "extensions"
    shutil.rmtree(extensions_dir)
    distributed_config = extensions_dir / "pi-tool-display" / "config.json"
    distributed_config.parent.mkdir(parents=True)
    distributed_config.write_bytes(config)
    distributed_mode_extension = agent_dir / FFF_MODE_EXTENSION_PATH
    distributed_mode_extension.parent.mkdir(parents=True, exist_ok=True)
    distributed_mode_extension.write_bytes(mode_extension)

    observer_dir = agent_dir / SMOKE_MODE_OBSERVER_PACKAGE
    observer_dir.mkdir()
    (observer_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "smoke-mode-observer",
                "version": "0.0.0",
                "type": "module",
                "pi": {"extensions": ["index.js"]},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (observer_dir / "index.js").write_text(
        "export default function smokeModeObserver() {\n"
        f"  console.error({json.dumps(SMOKE_MODE_MARKER)} + (process.env.PI_FFF_MODE ?? \"\"));\n"
        "}\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(
            {"packages": [f"./{SMOKE_MODE_OBSERVER_PACKAGE.as_posix()}"]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _isolated_env(agent_dir: Path, home_dir: Path, *, install: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    env["HOME"] = str(home_dir)
    env["XDG_CONFIG_HOME"] = str(home_dir / ".config")
    env["XDG_DATA_HOME"] = str(home_dir / ".local" / "share")
    if install:
        env.pop("PI_OFFLINE", None)
    else:
        env["PI_OFFLINE"] = "1"
    return env


def _install_packages(
    pi_path: Path,
    agent_dir: Path,
    package_specs: Sequence[str],
    home_dir: Path,
    timeout: float,
) -> None:
    env = _isolated_env(agent_dir, home_dir, install=True)
    for package in package_specs:
        result = _run(
            [str(pi_path), "install", package, "--no-approve"],
            timeout=timeout,
            env=env,
        )
        _require_success(result, f"install {package}")


def _parse_rpc_output(output: str) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise SmokeError(f"RPC outputにJSON以外の行があります: {line!r}") from error
        if not isinstance(message, dict):
            raise SmokeError("RPC outputのmessageがobjectではありません")
        messages.append(message)
    return messages


def _response_by_id(messages: Sequence[dict[str, object]], request_id: str) -> dict[str, object]:
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise SmokeError(f"RPC responseがありません: {request_id}")


def _run_mode(
    pi_path: Path,
    repo_root: Path,
    agent_dir: Path,
    home_dir: Path,
    mode: str | None,
    timeout: float,
) -> None:
    mode_label = "default" if mode is None else mode
    commands = [
        {"id": "state", "type": "get_state"},
        {"id": "abort", "type": "abort"},
    ]
    input_text = "".join(json.dumps(command) + "\n" for command in commands)
    env = _isolated_env(agent_dir, home_dir, install=False)
    if mode is None:
        env.pop("PI_FFF_MODE", None)
    else:
        env["PI_FFF_MODE"] = mode
    result = _run(
        [
            str(pi_path),
            "--mode",
            "rpc",
            "--no-session",
            "--no-skills",
            "--no-context-files",
            "--offline",
        ],
        cwd=repo_root,
        env=env,
        input_text=input_text,
        timeout=timeout,
    )
    _require_success(result, f"Pi extension startup ({mode_label})")

    try:
        messages = _parse_rpc_output(result.stdout)
        state = _response_by_id(messages, "state")
        abort = _response_by_id(messages, "abort")
    except SmokeError as error:
        raise SmokeError(
            f"Pi extension startup ({mode_label}): {error}\n{_output(result)}"
        ) from error

    for request_id, response in (("state", state), ("abort", abort)):
        if response.get("success") is not True:
            raise SmokeError(
                f"Pi extension startup ({mode_label}): RPC {request_id} failed: {response}"
            )

    expected_mode = "override" if mode is None else mode
    observed_modes = [
        line[len(SMOKE_MODE_MARKER):].strip()
        for line in result.stderr.splitlines()
        if line.startswith(SMOKE_MODE_MARKER)
    ]
    if not observed_modes or any(observed != expected_mode for observed in observed_modes):
        raise SmokeError(
            f"Pi extension startup ({mode_label}): "
            f"FFF mode marker mismatch (expected {expected_mode!r}, observed {observed_modes!r})\n"
            f"{_output(result)}"
        )

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="harness repository root",
    )
    parser.add_argument("--pi", type=Path, default=None, help="検査するpi executable")
    parser.add_argument("--timeout", type=float, default=60.0, help="各処理のtimeout秒")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    pi_path = (args.pi or Path(shutil.which("pi") or "")).expanduser().resolve()
    if not pi_path.is_file():
        print("ERROR: pi executableが見つかりません", file=sys.stderr)
        return 1

    timeout = max(args.timeout, 0.1)
    try:
        package_specs = _target_package_specs(repo_root)
        with tempfile.TemporaryDirectory(prefix="pi-extension-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            base_agent_dir = temp_root / "base" / "agent"
            _prepare_agent_dir(repo_root, base_agent_dir, timeout)
            _install_packages(
                pi_path,
                base_agent_dir,
                package_specs,
                temp_root / "install-home",
                timeout,
            )

            for mode in (None,) + MODES:
                mode_label = "default" if mode is None else mode
                mode_root = temp_root / mode_label
                mode_agent_dir = mode_root / "agent"
                shutil.copytree(base_agent_dir, mode_agent_dir)
                _run_mode(
                    pi_path,
                    repo_root,
                    mode_agent_dir,
                    mode_root / "home",
                    mode,
                    timeout,
                )
                print(f"[OK] Pi extension startup ({mode_label})")
    except SmokeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Pi extension smoke: 0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

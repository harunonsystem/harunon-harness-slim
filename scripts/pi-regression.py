#!/usr/bin/env python3
"""Pi のproviderなし回帰スモークを実行する。

実LLMターンは実行しない。RPCの状態取得・abort・compaction状態公開と、
設定上のsubagent package pinだけを検査する。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


# subagent 拡張の npm package 名。settings.json の packages pin と対で使う契約文字列
# なので、フォークを乗り換えるときはここと packages/targets/pi/settings.json の 2 箇所を
# 揃える（`npm:<name>@<version>` の name 部分）。
SUBAGENT_PACKAGE = "@gotgenes/pi-subagents"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _run(
    argv: Sequence[str], *, input_text: str | None = None, timeout: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(argv),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _parse_json_lines(output: str) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError("RPC response is not an object")
        messages.append(parsed)
    return messages


def _response_by_id(messages: list[dict[str, object]], request_id: str) -> dict[str, object]:
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise ValueError(f"RPC response missing: {request_id}")


def _run_rpc(pi_path: Path, timeout: float) -> list[Result]:
    commands = [
        {"id": "state", "type": "get_state"},
        {"id": "abort", "type": "abort"},
    ]
    input_text = "".join(json.dumps(command) + "\n" for command in commands)
    with tempfile.TemporaryDirectory(prefix="pi-regression-") as home_dir:
        env = os.environ.copy()
        env["HOME"] = home_dir
        env["PI_OFFLINE"] = "1"
        result = _run(
            [
                str(pi_path),
                "--mode",
                "rpc",
                "--no-session",
                "--no-extensions",
                "--no-skills",
                "--no-context-files",
                "--offline",
            ],
            input_text=input_text,
            timeout=timeout,
            env=env,
        )
    if result is None:
        return [Result("rpc-process", "fail", "RPC processが起動または終了しませんでした")]
    if result.returncode != 0:
        return [Result("rpc-process", "fail", f"RPC exit={result.returncode}")]

    try:
        messages = _parse_json_lines(result.stdout)
        state_response = _response_by_id(messages, "state")
        abort_response = _response_by_id(messages, "abort")
    except (ValueError, json.JSONDecodeError) as error:
        return [Result("rpc-protocol", "fail", f"JSONL応答を解釈できません: {error}")]

    results = [
        Result("rpc-state-response", "ok" if state_response.get("success") is True else "fail", "get_state success"),
        Result("rpc-abort-response", "ok" if abort_response.get("success") is True else "fail", "idle abort success"),
    ]
    state = state_response.get("data")
    if not isinstance(state, dict):
        results.append(Result("compaction-state", "fail", "get_state.dataがobjectではありません"))
        return results

    expected = {
        "isStreaming": False,
        "isCompacting": False,
        "pendingMessageCount": 0,
    }
    mismatches = [
        f"{key}={state.get(key)!r} (expected {value!r})"
        for key, value in expected.items()
        if state.get(key) != value
    ]
    auto_compaction = state.get("autoCompactionEnabled")
    if not isinstance(auto_compaction, bool):
        mismatches.append("autoCompactionEnabled is not bool")
    if mismatches:
        results.append(Result("compaction-state", "fail", "; ".join(mismatches)))
    else:
        results.append(Result("compaction-state", "ok", "idle state and auto-compaction flag are valid"))
    return results


def _check_subagent_pin(agent_dir: Path) -> Result:
    settings_path = agent_dir / "settings.json"
    if not settings_path.is_file():
        return Result("subagent-package", "warn", "settings.jsonなし。package pinのみ未検査")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return Result("subagent-package", "fail", "settings.jsonを解釈できません")
    packages = settings.get("packages") if isinstance(settings, dict) else None
    if not isinstance(packages, list):
        return Result("subagent-package", "warn", "packagesなし。subagent package pinのみ未検査")
    matches = [
        package
        for package in packages
        if isinstance(package, str) and package.startswith(f"npm:{SUBAGENT_PACKAGE}@")
    ]
    if len(matches) == 1:
        return Result("subagent-package", "ok", "pi-subagents packageはversion pin済み（live LLM turnは未実行）")
    if not matches:
        return Result("subagent-package", "warn", "pi-subagents packageが設定されていません")
    return Result("subagent-package", "fail", "pi-subagents packageが複数設定されています")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", type=Path, default=None, help="検査するpi executable")
    parser.add_argument(
        "--agent-dir", type=Path, default=None, help="Pi agent directory（既定: $HOME/.pi/agent）"
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="RPC timeout秒")
    parser.add_argument("--skip-subagent-config", action="store_true")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pi_path = (args.pi or Path(shutil.which("pi") or "")).expanduser()
    results: list[Result] = []
    if not pi_path.is_file():
        results.append(Result("pi-command", "fail", "pi executableが見つかりません"))
    else:
        version = _run([str(pi_path), "--version"], timeout=max(args.timeout, 0.1))
        if version is None or version.returncode != 0 or not version.stdout.strip():
            results.append(Result("pi-version", "fail", "pi --versionに失敗しました"))
        else:
            results.append(Result("pi-version", "ok", version.stdout.splitlines()[0].strip()))
            results.extend(_run_rpc(pi_path, max(args.timeout, 0.1)))

    if not args.skip_subagent_config:
        agent_dir = (args.agent_dir or Path.home() / ".pi" / "agent").expanduser().resolve()
        results.append(_check_subagent_pin(agent_dir))

    failures = sum(result.status == "fail" for result in results)
    warnings = sum(result.status == "warn" for result in results)
    if args.json:
        print(
            json.dumps(
                {"results": [asdict(result) for result in results], "summary": {"failures": failures, "warnings": warnings}},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in results:
            print(f"[{result.status.upper()}] {result.name}: {result.detail}")
        print(f"Summary: {failures} failure(s), {warnings} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

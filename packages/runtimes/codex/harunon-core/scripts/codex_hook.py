#!/usr/bin/env python3
"""Translate Codex hook events into runtime-neutral workflow intents."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOKS = PLUGIN_ROOT / "hooks"
PIPELINE_TABLE = PLUGIN_ROOT / "policy" / "hook-pipeline.json"
# write/edit 後の品質チェック（runtime 中立 shell。build-codex-plugin.py が同梱する）
POST_EDIT_CHECKS = HOOKS / "post-edit" / "post-edit-checks.sh"
# Codex の編集ツール名 → hook-pipeline.json の when.tools / hooks/*.sh が使う Claude 名。
# pi の claude-hooks-bridge における PI_TO_CLAUDE_TOOL と同じ役割で、これが無いと
# block-edit-on-main.sh（tool_name が Edit|Write 以外を素通しする）に届かない。
# apply_patch は file_path を持たず patch envelope を運ぶため Write に寄せる。
CODEX_TO_CLAUDE_TOOL = {
    "write": "Write",
    "write_file": "Write",
    "apply_patch": "Write",
    "edit": "Edit",
    "edit_file": "Edit",
}
EDIT_TOOLS = frozenset(CODEX_TO_CLAUDE_TOOL)
# JS hook-runner の DEFAULT_TIMEOUT_MS = 60_000 と同じ上限。PreToolUse の hook が
# 無期限にぶら下がると、Codex 側の tool call 全体も返らなくなる。
HOOK_TIMEOUT_SECONDS = 60
# PreToolUse で pipeline に載せるツール。ここに無いツールは hook を通さない。
PRE_TOOL_USE_TOOLS = {
    "bash": "Bash",
    "enterworktree": "EnterWorktree",
    **CODEX_TO_CLAUDE_TOOL,
}


def hook_env() -> dict[str, str]:
    """Return the runtime environment shared by every shell hook invocation."""
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    for entry in ("/bin", "/usr/bin"):
        if entry not in entries:
            entries.append(entry)
    return {**os.environ, "PATH": os.pathsep.join(entries), "HARNESS_RUNTIME": "codex"}


_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)


def deny(action: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Core Workflow blocked {action}: {reason}"
            ),
        }
    }


def session_cwd(event: dict[str, Any]) -> Path:
    """イベントが運ぶセッションの base cwd を解決する。

    CMD 文字列に含まれる `cd` の抽出はここでは行わない（shell 側の
    共有 resolver の責務。両方が独自に解決すると P1-A のように base を
    黙って破棄する不整合が起きる）。
    """
    tool_input = event.get("tool_input", {})
    tool_workdir = tool_input.get("workdir") or tool_input.get("cwd")
    return Path(tool_workdir or event.get("cwd") or os.getcwd()).expanduser().resolve()


def codex_pipeline() -> list[dict[str, Any]]:
    """hook-pipeline.json（SSOT）から codex に配線された hook を order 昇順で返す。

    以前は tuple への positional index で hook を選択していたため、tuple を並べ替えると
    各条件が別の hook を選ぶのに validator は集合一致しか見ていなかった。選択条件も
    table 側の when に持たせ、hook 自身の述語（block-grep の grep 判定など）を
    dispatcher が二重に持たないようにする。
    """
    table = json.loads(PIPELINE_TABLE.read_text(encoding="utf-8"))
    hooks = [h for h in table["hooks"] if "codex" in h["runtimes"]]
    hooks.sort(key=lambda h: h["order"])
    return hooks


def claude_tool_name(event: dict[str, Any]) -> str:
    """Codex のツール名を hook 側の Claude 名へ正規化する。対象外なら空文字。"""
    raw = str(event.get("tool_name") or event.get("tool") or "")
    return PRE_TOOL_USE_TOOLS.get(raw.lower(), "")


def candidate_hooks(event: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """tool に掛かる hook を返す。command 条件は updatedInput ごとに実行時評価する。"""
    tool = claude_tool_name(event).lower()
    hooks: list[dict[str, Any]] = []

    for hook in codex_pipeline():
        when = hook.get("when") or {}
        tools = [name.lower() for name in (when.get("tools") or [])]
        if tools and tool not in tools:
            continue
        hooks.append(hook)
    return tuple(hooks)


def run_shell_pipeline(event: dict[str, Any], repo: Path) -> tuple[int, str]:
    env = hook_env()
    tool_input = dict(event.get("tool_input") or {})
    input_changed = False
    for hook in candidate_hooks(event):
        pattern = (hook.get("when") or {}).get("commandEre")
        command = str(tool_input.get("command") or "")
        if pattern and not re.search(pattern, command):
            continue
        name = hook["file"]
        required = hook.get("required") is True
        try:
            result = subprocess.run(
                ["bash", str(HOOKS / name)],
                input=json.dumps({**event, "tool_input": tool_input}),
                cwd=repo,
                capture_output=True,
                text=True,
                env=env,
                timeout=HOOK_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            message = f"hook timed out after {HOOK_TIMEOUT_SECONDS}s: {name}"
            if required:
                return 1, f"required security {message}"
            print(f"warning: {message}", file=sys.stderr)
            continue
        output = result.stdout.strip()
        if result.returncode != 0:
            reason = "\n".join(
                part for part in (output, result.stderr.strip()) if part
            )
            if result.returncode == 2 or required:
                return result.returncode, reason
            continue
        if output:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                if required:
                    return 1, f"required security hook stdout is not JSON: {name}"
                continue
            hook_output = payload.get("hookSpecificOutput") or {}
            reason = str(hook_output.get("permissionDecisionReason") or "")
            # Codex は PreToolUse の permissionDecision:ask を unsupported として拒否する
            # （codex-cli 0.146.1 のバリデーションエラー "PreToolUse hook returned
            # unsupported permissionDecision:ask"）。素通しすると確認したかった操作が
            # 黙って通るので、確認 UI を持たない opencode / omp と同じく deny に倒す。
            if hook_output.get("permissionDecision") in {"deny", "ask"}:
                return 2, reason
            updated_input = hook_output.get("updatedInput")
            if isinstance(updated_input, dict):
                tool_input.update(updated_input)
                input_changed = True
    if input_changed:
        # updatedInput は permissionDecision:allow と対でしか受理されない
        # （"PreToolUse hook returned updatedInput without permissionDecision:allow"）
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": tool_input,
            }
        }, ensure_ascii=False))
    return 0, ""


def edited_paths(event: dict[str, Any]) -> list[str]:
    """PostToolUse イベントが触ったファイルを返す（apply_patch は patch 本文から抽出）。"""
    tool_input = event.get("tool_input") or {}
    direct = tool_input.get("file_path") or tool_input.get("path")
    if isinstance(direct, str):
        return [direct]
    patch = tool_input.get("patch") or tool_input.get("input") or ""
    if not isinstance(patch, str):
        return []
    return [m.strip() for m in _PATCH_FILE_RE.findall(patch)]


def post_edit_context(event: dict[str, Any]) -> str:
    """post-edit-checks.sh を各ファイルに掛け、指摘を additionalContext 用に連結する。

    指摘はモデルが自己修正するための追記なので、script 側の失敗も含めて deny には倒さない。
    """
    if not POST_EDIT_CHECKS.is_file():
        return ""
    base = session_cwd(event)
    findings: list[str] = []
    for raw in edited_paths(event):
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        # JS 双子（opencode / omp）と同じ 30 秒上限。巨大ファイルの shellcheck で
        # PostToolUse を無期限に待たせない。advisory なので timeout は無言で次へ
        try:
            result = subprocess.run(
                ["bash", str(POST_EDIT_CHECKS), str(path)],
                capture_output=True, text=True, check=False, timeout=30,
                env=hook_env(),
            )
        except subprocess.TimeoutExpired:
            continue
        output = result.stdout.strip()
        if output:
            findings.append(f"{raw}\n{output}")
    return "\n\n".join(findings)


def run_post_tool_use(event: dict[str, Any]) -> int:
    tool = str(event.get("tool_name") or event.get("tool") or "").lower()
    if tool not in EDIT_TOOLS:
        return 0
    context = post_edit_context(event)
    if context:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"[post-edit-check]\n{context}",
                    }
                },
                ensure_ascii=False,
            )
        )
    return 0


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("hook_event_name") == "PostToolUse":
        return run_post_tool_use(event)
    tool = claude_tool_name(event)
    if not tool:
        return 0
    # table が読めないと配線が判定できない。guard の欠落を無言で通さず deny に倒す。
    if not PIPELINE_TABLE.is_file():
        print(
            json.dumps(
                deny("shell.guard", f"hook pipeline table が読めません: {PIPELINE_TABLE}"),
                ensure_ascii=False,
            )
        )
        return 0
    repo = session_cwd(event)
    # base cwd が存在しないと subprocess.run(cwd=repo) が FileNotFoundError で
    # 例外送出し、pipeline 全体が exit 1 + traceback で fail-open してしまう
    # （P1-A）。table 不在と同じ規律で deny に倒す。
    if not repo.is_dir():
        print(
            json.dumps(
                deny("shell.guard", f"セッションの base cwd が存在しません: {repo}"),
                ensure_ascii=False,
            )
        )
        return 0
    # hooks/*.sh は Claude のツール名で分岐する（block-edit-on-main.sh は Edit|Write
    # 以外を素通しする）。matcher だけでなくイベント本体も正規化して渡す。
    code, reason = run_shell_pipeline({**event, "tool_name": tool}, repo)
    if code != 0:
        print(json.dumps(deny("shell.guard", reason), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

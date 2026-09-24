#!/usr/bin/env python3
"""Portable friendly adapter for the Core Workflow JSON interface."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def locate_kernel() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "policy/harnessctl.py",
        Path.home() / ".codex/policy/harnessctl.py",
        Path.home() / ".config/opencode/policy/harnessctl.py",
        Path.home() / ".claude/policy/harnessctl.py",
        Path.home() / ".pi/agent/policy/harnessctl.py",
        Path.home() / ".omp/agent/policy/harnessctl.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Core Workflow kernel is not installed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    start = commands.add_parser("start")
    start.add_argument("task_id")
    start.add_argument("--publish-only", action="store_true")
    advance = commands.add_parser("advance")
    advance.add_argument("event")
    advance.add_argument("--revision", type=int, required=True)
    approve = commands.add_parser("approve-review")
    approve.add_argument("--revision", type=int, required=True)
    approve.add_argument("--reason", required=True)
    attach = commands.add_parser("attach-review")
    attach.add_argument("--revision", type=int, required=True)
    attach.add_argument("--provider", required=True)
    attach.add_argument("--subject-sha", required=True)
    attach.add_argument("--artifact", type=Path, required=True)
    skip = commands.add_parser("skip-review")
    skip.add_argument("--revision", type=int, required=True)
    skip.add_argument("--provider", required=True)
    skip.add_argument("--reason", required=True)
    authorize = commands.add_parser("authorize")
    authorize.add_argument("action", choices=("pr.create", "pr.merge"))
    assign = commands.add_parser("assign")
    assign.add_argument("role", choices=("implement", "review"))
    assign.add_argument("--executor", required=True)
    assign.add_argument("--worker-id", required=True)
    assign.add_argument("--revision", type=int, required=True)
    dispatched = commands.add_parser("dispatched")
    dispatched.add_argument("--transport", required=True)
    dispatched.add_argument("--ref", required=True)
    dispatched.add_argument("--at", required=True)
    dispatched.add_argument("--revision", type=int, required=True)
    report = commands.add_parser("report")
    report.add_argument("--revision", type=int, required=True)
    report.add_argument("--executor", required=True)
    report.add_argument("--worker-id", required=True)
    report.add_argument("--result-sha", required=True)
    report.add_argument("--artifact", type=Path, required=True)
    report.add_argument("--checks", default="[]")
    abandon = commands.add_parser("abandon")
    abandon.add_argument("--reason", required=True)
    abandon.add_argument("--revision", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    operation = "inspect" if args.command == "status" else args.command.replace("-", "_")
    arguments: dict[str, object] = {}
    if operation == "start":
        arguments = {
            "taskId": args.task_id,
            "mode": "publish" if args.publish_only else "change",
        }
    elif operation == "advance":
        arguments = {"event": args.event, "expectedRevision": args.revision}
    elif operation == "approve_review":
        arguments = {"reason": args.reason, "expectedRevision": args.revision}
    elif operation == "attach_review":
        arguments = {
            "provider": args.provider,
            "subjectSha": args.subject_sha,
            "artifact": str(args.artifact.expanduser().resolve()),
            "expectedRevision": args.revision,
        }
    elif operation == "skip_review":
        arguments = {
            "provider": args.provider,
            "reason": args.reason,
            "expectedRevision": args.revision,
        }
    elif operation == "authorize":
        arguments = {"action": args.action}
    elif operation == "assign":
        arguments = {
            "role": args.role,
            "executor": args.executor,
            "workerId": args.worker_id,
            "expectedRevision": args.revision,
        }
    elif operation == "dispatched":
        arguments = {
            "transport": args.transport,
            "ref": args.ref,
            "at": args.at,
            "expectedRevision": args.revision,
        }
    elif operation == "report":
        arguments = {
            "executor": args.executor,
            "workerId": args.worker_id,
            "resultSha": args.result_sha,
            "artifact": str(args.artifact.expanduser().resolve()),
            "checks": args.checks,
            "expectedRevision": args.revision,
        }
    elif operation == "abandon":
        arguments = {"reason": args.reason, "expectedRevision": args.revision}
    result = subprocess.run(
        [sys.executable, str(locate_kernel()), "operate"],
        input=json.dumps(
            {
                "repo": str(args.repo.resolve()),
                "operation": operation,
                "arguments": arguments,
            }
        ),
        capture_output=True,
        text=True,
    )
    print(result.stdout or result.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

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
    if args.command == "status":
        kernel_command, request = "inspect", {}
    elif args.command == "start":
        kernel_command, request = "apply", {
            "type": "task.start",
            "taskId": args.task_id,
            "mode": "publish" if args.publish_only else "change",
        }
    elif args.command == "advance":
        kernel_command, request = "apply", {
            "type": "phase.advance",
            "event": args.event,
            "expectedRevision": args.revision,
        }
    elif args.command == "approve-review":
        kernel_command, request = "apply", {
            "type": "review.approve",
            "reason": args.reason,
            "expectedRevision": args.revision,
        }
    elif args.command == "attach-review":
        artifact = args.artifact.expanduser().resolve()
        if not artifact.is_file():
            print(json.dumps({"code": "REVIEW_ARTIFACT_NOT_FOUND", "artifact": str(artifact)}))
            return 2
        kernel_command, request = "apply", {
            "type": "review.attach",
            "expectedRevision": args.revision,
            "evidence": {
                "kind": "local-review",
                "trust": "audit-only",
                "provider": args.provider,
                "subjectSha": args.subject_sha,
                "artifact": str(artifact),
            },
        }
    elif args.command == "skip-review":
        # quota / credit 切れで reviewer が返らなかったときだけ。他の失敗は止まって確認する
        kernel_command, request = "apply", {
            "type": "review.skip",
            "expectedRevision": args.revision,
            "evidence": {
                "kind": "review-skipped",
                "trust": "audit-only",
                "provider": args.provider,
                "skipReason": "quota",
                "reason": args.reason,
            },
        }
    elif args.command == "authorize":
        kernel_command, request = "authorize", {"action": args.action}
    elif args.command == "assign":
        kernel_command, request = "apply", {
            "type": "assignment.create",
            "expectedRevision": args.revision,
            "role": args.role,
            "executor": args.executor,
            "workerId": args.worker_id,
        }
    elif args.command == "dispatched":
        try:
            ref = json.loads(args.ref)
        except json.JSONDecodeError as error:
            print(json.dumps({"code": "INVALID_JSON", "reason": str(error)}))
            return 3
        kernel_command, request = "apply", {
            "type": "assignment.dispatched",
            "expectedRevision": args.revision,
            "transport": args.transport,
            "ref": ref,
            "at": args.at,
        }
    elif args.command == "report":
        artifact = args.artifact.expanduser().resolve()
        if not artifact.is_file():
            print(json.dumps({"code": "REVIEW_ARTIFACT_NOT_FOUND", "artifact": str(artifact)}))
            return 2
        try:
            checks = json.loads(args.checks)
        except json.JSONDecodeError as error:
            print(json.dumps({"code": "INVALID_JSON", "reason": str(error)}))
            return 3
        kernel_command, request = "apply", {
            "type": "assignment.report",
            "expectedRevision": args.revision,
            "evidence": {
                "kind": "worker-report",
                "trust": "audit-only",
                "executor": args.executor,
                "workerId": args.worker_id,
                "resultSha": args.result_sha,
                "artifact": str(artifact),
                "checks": checks,
            },
        }
    else:
        kernel_command, request = "apply", {
            "type": "assignment.abandon",
            "expectedRevision": args.revision,
            "reason": args.reason,
        }
    result = subprocess.run(
        [sys.executable, str(locate_kernel()), kernel_command],
        input=json.dumps({"repo": str(args.repo.resolve()), **request}),
        capture_output=True,
        text=True,
    )
    print(result.stdout or result.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

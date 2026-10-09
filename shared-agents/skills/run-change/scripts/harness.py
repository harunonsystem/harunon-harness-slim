#!/usr/bin/env python3
"""Portable friendly adapter for the Core Workflow JSON interface."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


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
    status = commands.add_parser("status")
    status.add_argument("--pr", nargs="?", const="", help="read-only GitHub PR reconciliation; omit number to find the current branch")
    verify = commands.add_parser("verify")
    verify.add_argument("--revision", type=int, required=True)
    complete = commands.add_parser("complete")
    complete.add_argument("--revision", type=int, required=True)
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


def reconcile_pr(repo: Path, selector: str) -> dict:
    """Observe GitHub without mutating workflow state or granting publication."""
    sys.path.insert(0, str(locate_kernel().parent))
    from repo_target import UnresolvableTarget, repository_identity

    def read(command: list[str]) -> str:
        return subprocess.run(command, cwd=repo, capture_output=True, text=True, check=True, timeout=30).stdout.strip()

    try:
        identity = repository_identity(repo)
        if not re.fullmatch(r"github\.com/[\w.-]+/[\w.-]+", identity):
            raise ValueError("canonical github.com repository required")
        repository = identity.removeprefix("github.com/")
        git = ["git", "-C", str(repo)]
        local_head = read(git + ["rev-parse", "HEAD"])
        branch = read(git + ["symbolic-ref", "--short", "HEAD"])
        upstream = read(git + ["for-each-ref", "--format=%(upstream:remotename)%09%(upstream:remoteref)", "refs/heads/" + branch])
        if upstream:
            remote, ref = upstream.split("\t")
            if remote == "." or not ref.startswith("refs/heads/"):
                raise ValueError("GitHub upstream branch unavailable")
            branch = ref.removeprefix("refs/heads/")
        number = selector.lower().removeprefix(f"https://github.com/{repository}/pull/")
        projection = "{number,html_url,state,merged_at,merge_commit_sha,head:.head.sha,headRepo:.head.repo.full_name,headRef:.head.ref,base:.base.repo.full_name}"
        endpoint = f"repos/{repository}/pulls"
        if selector:
            if not re.fullmatch(r"[1-9][0-9]*", number):
                raise ValueError("PR number or matching canonical URL required")
            endpoint += f"/{number}"
        else:
            endpoint += "?state=all&per_page=100&head=" + quote(repository.split("/")[0] + ":" + branch, safe="")
            projection = "[.[] | " + projection + "]"
        data = json.loads(read(["gh", "api", "--hostname", "github.com", endpoint, "--jq", projection]))
        if not selector:
            if not isinstance(data, list) or len(data) > 1:
                raise ValueError("PR candidates are ambiguous")
            if not data:
                return {"state": "ABSENT", "repository": identity, "localHead": local_head, "nextAction": "no-existing-pr"}
            data = data[0]
        if not isinstance(data, dict):
            raise ValueError("invalid PR response")
        n, head = data.get("number"), data.get("head", "")
        if (type(n) is not int or n < 1 or (selector and str(n) != number)
                or data.get("html_url", "").lower() != f"https://github.com/{repository}/pull/{n}"
                or data.get("base", "").lower() != repository
                or data.get("headRepo", "").lower() != repository
                or data.get("headRef") != branch
                or not re.fullmatch(r"[0-9a-f]{40}", head)
                or data.get("state") not in ("open", "closed")):
            raise ValueError("PR identity or HEAD unavailable/mismatched")
        merged = data.get("merged_at") is not None
        if merged and (not isinstance(data["merged_at"], str) or not data["merged_at"] or data["state"] != "closed"):
            raise ValueError("invalid merge state")
        state = "MERGED" if merged else data["state"].upper()
        observation = {"state": state, "repository": identity, "number": n, "url": data["html_url"],
                       "head": head, "localHead": local_head, "headMatches": head == local_head,
                       "nextAction": "stop-old-work" if state != "OPEN" else "reuse-pr" if head == local_head else "reconcile-head"}
        merge_sha = data.get("merge_commit_sha")
        if merged and isinstance(merge_sha, str) and re.fullmatch(r"[0-9a-f]{40}", merge_sha):
            # Message evidence only; this does not infer the current net effect of a revert.
            try:
                observation["revertMessageCommits"] = read(git + ["log", "--format=%H", "--fixed-strings", "--grep=This reverts commit " + merge_sha + ".", "HEAD"]).splitlines()
            except (OSError, subprocess.SubprocessError) as error:
                observation["revertEvidenceUnavailable"] = str(error)
        return observation
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError, UnresolvableTarget) as error:
        return {"state": "UNKNOWN", "reason": str(error)}


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
    elif operation in ("verify", "complete"):
        arguments = {"expectedRevision": args.revision}
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
    if args.command == "status" and args.pr is not None:
        observation = reconcile_pr(args.repo.resolve(), args.pr)
        status_unavailable = False
        try:
            workflow = json.loads(result.stdout)
        except ValueError:
            workflow = {"error": result.stderr or "workflow status unavailable"}
            status_unavailable = True
        print(json.dumps({"workflow": workflow, "pr": observation}, ensure_ascii=False))
        return result.returncode or (2 if status_unavailable or observation["state"] == "UNKNOWN" else 0)
    print(result.stdout or result.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

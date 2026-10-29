"""Narrow, same-invocation publication to the current worktree's own PR."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from publication_body import digest
from repo_target import canonical_repository, process_env_overrides_git, repository_identity

GH_INSTALL_PATHS = ("/usr/bin/gh", "/usr/local/bin/gh", "/opt/homebrew/bin/gh")


class OwnPrError(Exception):
    pass


def publish(repo: Path, kernel: Path, *, operation: str, hostname: str,
            repository: str, number: int, body_file: Path, task_id: str) -> dict:
    repo = repo.resolve(strict=True)
    # GIT_CONFIG_COUNT は worktree セッションの sandbox が safe.directory 用に注入するので、送信先を変える key だけ拒否する
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")) \
            or process_env_overrides_git("GIT_CONFIG_COUNT"):
        raise OwnPrError("Git context overrides cannot establish this worktree's PR")
    if (operation not in ("comment", "update-body") or type(number) is not int or number < 1
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname)
            or "." not in hostname or ".." in hostname
            or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository)
            or repository.split("/")[1] in (".", "..") or not task_id.strip()):
        raise OwnPrError("Explicit hostname, owner/repo, positive PR, operation and task ID required")
    identity = canonical_repository(f"https://{hostname}/{repository}")
    if repository_identity(repo) != identity:
        raise OwnPrError("Target differs from this worktree's repository")
    path = body_file.expanduser().resolve(strict=True)
    if (not path.is_file() or path.suffix.lower() not in (".md", ".txt") or path.stat().st_size > 65536
            or any(part == ".env" or part.startswith(".env.") or part in
                   (".ssh", ".aws", ".kube", "gh") for part in path.parts)):
        raise OwnPrError("A regular, non-secret final body file of at most 64 KiB is required")
    body = path.read_bytes().decode("utf-8")
    if not body.strip() or "\0" in body:
        raise OwnPrError("A non-empty UTF-8 final body is required")
    # High-confidence patterns, not a claim that arbitrary confidential prose is safe.
    if re.search(r"AKIA[0-9A-Z]{16}|-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY|"
                 r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
                 r"sk-ant-[A-Za-z0-9-]{20,}", body):
        raise OwnPrError("Possible secret in final body; publication refused")

    executable = shutil.which("gh")
    if not executable:
        raise OwnPrError("GitHub CLI unavailable")
    gh = Path(executable).resolve(strict=True)
    if gh.is_relative_to(repo) or not any(Path(entry).resolve() == gh for entry in GH_INSTALL_PATHS):
        raise OwnPrError("gh must resolve to a supported system installation; custom PATH wrappers are refused")
    # Inherit credentials opaquely; never query tokens, serialize the environment,
    # or use auth-status's account (which can differ from an environment token).
    for key in ("GH_DEBUG", "DEBUG"):
        os.environ.pop(key, None)
    os.environ["GH_PROMPT_DISABLED"] = "1"

    def run(argv: list[str], payload: dict | None = None) -> dict:
        try:
            result = subprocess.run(argv, cwd=repo, text=True,
                                    input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, timeout=30)
            if result.returncode:
                raise OwnPrError("Command failed; no automatic retry (check remote outcome for a write)")
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError("object required")
            return value
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            # Do not echo subprocess output, argv, payload or credential diagnostics.
            raise OwnPrError("Command unavailable or response unknown; check remote outcome before retrying") from error

    def workflow(operation: str, arguments: dict) -> dict:
        return run([sys.executable, str(kernel), "operate"],
                   {"repo": str(repo), "operation": operation, "arguments": arguments})

    status = workflow("inspect", {})
    state = status.get("state", {})
    if state.get("task", {}).get("id") != task_id or state.get("phase") not in ("publish", "complete"):
        raise OwnPrError("Current workflow task ID or publication phase does not match")
    action = "pr.comment" if operation == "comment" else "pr.update-body"
    request = {"action": action}
    if operation == "update-body":
        request["publication"] = {"body": body, "repository": identity, "number": number}
    decision = workflow("authorize", request)
    if decision.get("allowed") is not True:
        raise OwnPrError("Existing verification/review/publication gate refused the operation")

    api = [str(gh), "api", "--hostname", hostname]
    viewer = run([*api, "--method", "GET", "user"])
    pr_path = f"repos/{repository}/pulls/{number}"
    pr = run([*api, "--method", "GET", pr_path])
    author = pr.get("user", {})
    login = viewer.get("login")
    if (not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login)
            or viewer.get("type") != "User" or author.get("type") != "User"
            or type(viewer.get("id")) is not int or viewer["id"] < 1
            or type(author.get("id")) is not int
            or viewer["id"] != author.get("id")
            or not isinstance(author.get("login"), str) or login.lower() != author["login"].lower()):
        raise OwnPrError("Effective GitHub user is unknown or is not the PR author")
    url = f"https://{hostname}/{repository}/pull/{number}"
    head = pr.get("head", {})
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    branch = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo,
                            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if (type(pr.get("number")) is not int or pr["number"] != number or pr.get("state") != "open"
            or pr.get("merged_at") is not None or str(pr.get("html_url", "")).lower() != url.lower()
            or str(pr.get("base", {}).get("repo", {}).get("full_name", "")).lower() != repository.lower()
            or str(head.get("repo", {}).get("full_name", "")).lower() != repository.lower()
            or not re.fullmatch(r"[0-9a-f]{40}", git_head) or head.get("sha") != git_head
            or not branch or head.get("ref") != branch):
        raise OwnPrError("Open PR host/repository/number/HEAD/branch does not match this worktree")

    if operation == "update-body":
        records = [item for item in state.get("evidence", []) if item.get("kind") == "publication-body"]
        previous = records[-1].get("publication", {}).get("target", {}).get("previousBodySha256") if records else None
        observed = pr.get("body")
        if (not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{64}", previous)
                or (observed is not None and not isinstance(observed, str))
                or digest(observed or "") not in (previous, digest(body))):
            raise OwnPrError("PR body changed or its attested version is unknown; reconcile before updating")
    # Recheck freshness after network reads; never reuse the earlier readiness decision.
    if workflow("authorize", request).get("allowed") is not True:
        raise OwnPrError("Final publication gate refused the operation")

    # No shell, arbitrary endpoint, flags, headers, comment IDs or persisted permit.
    # The exact in-memory body that passed the gate is the only writable field.
    method, endpoint = (("POST", f"repos/{repository}/issues/{number}/comments")
                        if operation == "comment" else ("PATCH", pr_path))
    result = run([*api, "--method", method, endpoint, "--input", "-"], {"body": body})
    if result.get("body") != body:
        raise OwnPrError("Write outcome uncertain: read back the target before retrying")
    return {"operation": operation, "repository": identity, "number": number, "url": url,
            "author": login, "status": "published"}

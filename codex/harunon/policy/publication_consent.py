#!/usr/bin/env python3
"""Check standing user consent; never grant native permission or publication evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from repo_target import (UnresolvableTarget, _git, _tokenize, checkout_identity,
                         gh_target_reason, git_environment_reason, push_target, repository_identity)


OPERATIONS = ("git.commit", "git.push", "pr.create")
DECLARATION = Path.home() / ".agents/policy/publication-consent.json"


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate consent declaration key")
        result[key] = value
    return result


def _scopes() -> list[dict]:
    data = json.loads(DECLARATION.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {"version", "scopes"} or type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["scopes"], list):
        raise ValueError("Invalid standing consent declaration")
    for scope in data["scopes"]:
        if not isinstance(scope, dict) or set(scope) != {"root", "host", "owner", "operations"}:
            raise ValueError("Invalid standing consent scope")
        if not all(isinstance(scope[key], str) and scope[key] for key in ("root", "host", "owner")):
            raise ValueError("Invalid standing consent identity")
        if not Path(scope["root"]).expanduser().is_absolute() or not re.fullmatch(r"[\w.-]+", scope["owner"]) or scope["host"] != "github.com":
            raise ValueError("Consent requires an absolute checkout root and GitHub owner")
        if not isinstance(scope["operations"], list) or not scope["operations"] or any(op not in OPERATIONS for op in scope["operations"]):
            raise ValueError("Invalid standing consent operations")
    return data["scopes"]


def _arguments(tokens: list[str], values: set[str], flags: set[str], *, positional: bool = False) -> None:
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        cursor += 1
        if token in flags:
            continue
        if token in values and cursor < len(tokens):
            cursor += 1
            continue
        if any(token.startswith(option + "=") or (len(option) == 2 and token.startswith(option) and len(token) > 2)
               for option in values):
            continue
        if positional and not token.startswith(("-", "+")):
            continue
        raise UnresolvableTarget("Standing consent does not cover this option or command")


def _command(operation: str, command: str) -> str | None:
    tokens = _tokenize(command)
    directory = None
    if any(token in {";", "&&", "||", "|", "&", "(", ")"} or any(char in token for char in ("$", "`", ">", "<")) for token in tokens):
        raise UnresolvableTarget("Standing consent requires one literal command")
    if tokens[:1] == ["env"]:
        tokens = tokens[1:]
    while tokens and re.match(r"^GH_(REPO|HOST)=", tokens[0]) and operation == "pr.create":
        tokens = tokens[1:]
    if tokens[:1] == ["command"]:
        tokens = tokens[1:]
    if tokens[:1] == ["rtk"]:
        tokens = tokens[1:]
    if operation.startswith("git."):
        if tokens[:1] != ["git"]:
            raise UnresolvableTarget("Expected a git command")
        tokens = tokens[1:]
        if tokens[:1] == ["-C"] and len(tokens) > 2:
            directory = tokens[1]
            if directory.startswith("~") or any(char in directory for char in "*?[]{}"):
                raise UnresolvableTarget("Standing consent requires a literal absolute or relative git -C path")
            tokens = tokens[2:]
        if tokens[:1] != [operation.removeprefix("git.")]:
            raise UnresolvableTarget("Git operation does not match consent request")
        tokens = tokens[1:]
        if operation == "git.commit":
            _arguments(tokens, {"-m", "--message", "-F", "--file", "-C", "--reuse-message"},
                       {"-a", "--all", "--no-edit", "--allow-empty", "--allow-empty-message", "-q", "--quiet", "-v", "--verbose"})
        else:
            _arguments(tokens, set(), {"-u", "--set-upstream", "-q", "--quiet", "-v", "--verbose", "--porcelain", "--dry-run", "-n"}, positional=True)
    else:
        if tokens[:3] != ["gh", "pr", "create"]:
            raise UnresolvableTarget("Expected PR creation")
        _arguments(tokens[3:], {"--repo", "-R", "--head", "-H", "--base", "-B", "--title", "-t", "--body", "-b", "--body-file", "-F",
                               "--assignee", "-a", "--label", "-l", "--milestone", "-m", "--project", "-p", "--reviewer", "-r", "--template", "-T"},
                   {"--draft", "-d", "--fill", "--fill-first", "--fill-verbose"})
    return directory


def check(base: Path, operation: str, command: str) -> dict:
    """Return a fresh resolved action; every runtime reads the shared global declaration."""
    scopes = _scopes()
    directory = _command(operation, command)
    reason = git_environment_reason(command)
    if reason or (operation == "pr.create" and os.environ.get("GH_CONFIG_DIR")):
        raise UnresolvableTarget(reason or "Custom gh configuration is outside standing consent")
    # Only the validated global -C selects a checkout; message/body values are data.
    repo = (base / directory if directory is not None else base).resolve(strict=True)
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    if branch in ("main", "master"):
        raise UnresolvableTarget("Protected heads are outside standing consent")
    repository = repository_identity(repo)
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)
    primary = common.parent
    # A lexical symlink or separate gitdir outside the enrolled root cannot enroll it.
    if common.name != ".git" or Path(_git(primary, "rev-parse", "--show-toplevel")).resolve() != primary:
        raise UnresolvableTarget("Physical primary checkout cannot be established")
    matched = any(operation in scope["operations"] and primary.parent == Path(scope["root"]).expanduser().resolve(strict=True)
                  and repository == scope["host"] + "/" + scope["owner"].lower() + "/" + primary.name.lower()
                  for scope in scopes)
    if not matched:
        raise UnresolvableTarget("No standing consent for the physical checkout and repository")
    if operation == "git.push":
        target = push_target(repo, command)
        if target["operation"] != operation or target["repository"] != repository:
            raise UnresolvableTarget("Actual push destination is outside standing consent")
    else:
        if operation == "pr.create":
            reason = gh_target_reason(command, branch, repo)
            if reason:
                raise UnresolvableTarget(reason)
        target = {"operation": operation, "checkout": checkout_identity(repo), "repository": repository,
                  "branch": branch, "head": _git(repo, "rev-parse", "HEAD"), "ref": "refs/heads/" + branch}
    return {"allowed": True, "target": target, "repo": str(Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()),
            "nativePermission": "unobserved"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = check(args.repo.resolve(), args.operation, sys.stdin.read())
    except (UnresolvableTarget, OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"allowed": False, "code": "NO_STANDING_CONSENT", "reason": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check or inherit the native gwm configuration for explicitly migrated clones.

Registry data lives outside checkouts. A directory prefix alone never grants
entry: the original common Gitdir, remote, and Git registration must agree.
Exit 3 means unmanaged; every other nonzero status fails closed.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def git(path, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    return subprocess.check_output(
        ["git", "-C", str(path), *args], env=env, stderr=subprocess.DEVNULL,
        timeout=10, text=True,
    ).strip()


def remote_identity(url):
    if "://" in url:
        parsed = urlsplit(url)
        host, path = parsed.hostname, parsed.path.lstrip("/")
    else:
        match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):([^?#]+)", url)
        if not match:
            raise ValueError("Unrecognized remote")
        host, path = match.groups()
    parts = path.rstrip("/").split("/")
    if len(parts) != 2 or not host:
        raise ValueError("Unrecognized remote path")
    name = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    return [host.lower(), parts[0].lower(), name]


def registered_roots(path):
    return {str(Path(value[9:]).resolve()) for value in
            git(path, "worktree", "list", "--porcelain", "-z").split("\0")
            if value.startswith("worktree ")}


def managed_entry(path):
    registry = Path.home() / ".config/gwm/ghq-migration.json"
    if not registry.is_file():
        raise SystemExit(3)
    entries = json.loads(registry.read_text())["repositories"]
    try:
        common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    except subprocess.CalledProcessError:
        raise SystemExit(3)
    entry = next((row for row in entries if row["common_dir"] == str(common)), None)
    if entry is None:
        raise SystemExit(3)
    info = common.stat()
    if [info.st_dev, info.st_ino] != entry["common_identity"]:
        raise ValueError("Common Gitdir identity changed")
    if remote_identity(git(path, "remote", "get-url", "origin")) != entry["origin"]:
        raise ValueError("Origin changed")
    if not any(remote_identity(git(path, "remote", "get-url", name)) == entry["selected"]
               for name in git(path, "remote").splitlines()):
        raise ValueError("Selected migration remote changed")
    return entry, common


def check_target(path, entry, common):
    root = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    gitdir = Path(git(path, "rev-parse", "--absolute-git-dir")).resolve()
    if gitdir.parent != common / "worktrees" or str(root) not in registered_roots(path):
        raise ValueError("Not a registered linked checkout")
    if Path((gitdir / "gitdir").read_text().strip()).resolve() != root / ".git":
        raise ValueError("Worktree backpointer mismatch")
    allowed_base = (Path(entry["base"]) / entry["origin"][2]).resolve()
    future = root.parent == allowed_base
    if str(root) not in entry["existing_worktrees"] and not future:
        raise ValueError("Not an approved worktree location")
    if Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != common:
        raise ValueError("Different clone")
    return root


def inherit(source, target):
    entry, common = managed_entry(source)
    root = check_target(target, entry, common)
    config = Path(entry["config"])
    expected = 'worktree_base_path = ' + json.dumps(entry["base"]) + '\n'
    if config.read_text() != expected:
        raise ValueError("Managed configuration changed")
    directory = root / ".gwm"
    if directory.is_symlink():
        raise ValueError("Refusing symlinked configuration directory")
    destination = directory / "config.toml"
    if destination.is_symlink() and destination.resolve() == config.resolve():
        return
    if os.path.lexists(destination) or (root / "gwm/config.toml").exists():
        raise ValueError("Preserving existing project configuration")
    directory.mkdir(exist_ok=True)
    destination.symlink_to(config)


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "check":
            entry, common = managed_entry(sys.argv[2])
            check_target(sys.argv[2], entry, common)
        elif len(sys.argv) == 4 and sys.argv[1] == "inherit":
            inherit(sys.argv[2], sys.argv[3])
        else:
            raise ValueError("Usage: managed-gwm-worktree.py check PATH | inherit SOURCE TARGET")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("[gwm managed] " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Bounded local Skill metadata and explicit, freshness-checked handoff."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from evidence_files import require_current, snapshot
from repo_target import repository_identity, UnresolvableTarget


def metadata(path: Path) -> dict:
    # The harness already pins PyYAML. Do not install dependencies or load YAML tags.
    try:
        import yaml
    except ImportError as error:
        raise ValueError("PyYAML unavailable; use the harness .venv Python (mise run deps)") from error
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ValueError(f"SKILL.md frontmatter missing: {path}")
    try:
        data = yaml.safe_load(text[4:].split("\n---", 1)[0])
    except yaml.YAMLError as error:
        raise ValueError(f"invalid Skill frontmatter: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"invalid Skill metadata: {path}")
    for field in ("name", "description"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Skill {field} missing: {path}")
    manual = data.get("disable-model-invocation", False)
    if not isinstance(manual, bool):
        raise ValueError(f"disable-model-invocation must be boolean: {path}")
    return {"name": data["name"], "description": data["description"], "manualOnly": manual}


def catalog(repo: Path, runtime: str, query: str, limit: int) -> dict:
    roots = [("project", repo / ".agents/skills"),
             ("runtime", Path.home() / {"codex": ".codex/skills", "pi": ".pi/agent/skills",
                                         "omp": ".omp/agent/skills", "claude": ".claude/skills",
                                         "opencode": ".config/opencode/skills"}[runtime]),
             ("shared", Path.home() / ".agents/skills")]
    entries, errors = [], []
    for provenance, root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/SKILL.md")):
            try:
                item = {**metadata(path), "provenance": provenance, "root": str(root),
                        "reference": snapshot(path, repo)}
                if query.casefold() not in (item["name"] + " " + item["description"]).casefold():
                    continue
                item["supportingPaths"] = [str(p.absolute()) for p in
                                           (path.parent / "config.yml", path.parent / "config.example.yml") if p.is_file()]
                entries.append(item)
            except (OSError, ValueError, UnicodeError) as error:
                errors.append({"path": str(path), "reason": str(error)})
    return {"protocol": "harness.skill-catalog.v1", "runtime": runtime,
            "entries": entries[:limit], "total": len(entries), "truncated": len(entries) > limit,
            "errors": errors[:limit], "errorTotal": len(errors), "selectionOwner": "parent", "nativeHostRegistration": "not implied"}


def context(task: dict) -> dict:
    required = ("taskId", "request", "arguments", "acceptance", "verification", "authority", "prohibitions",
                "resume", "reportDestination", "context")
    if not isinstance(task, dict) or any(key not in task for key in required):
        raise ValueError("task must include " + ", ".join(required))
    for key in ("taskId", "request", "reportDestination"):
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f"task {key} must be a non-empty string")
    if not isinstance(task["authority"], dict) or not isinstance(task["resume"], dict):
        raise ValueError("authority and resume must be objects; they do not grant native consent")
    if not isinstance(task["arguments"], (str, list, dict)):
        raise ValueError("original arguments must be a string, array, or object")
    for key in ("acceptance", "verification", "prohibitions"):
        if not isinstance(task[key], list) or not all(isinstance(v, str) for v in task[key]):
            raise ValueError(f"task {key} must be a string array")
    location = task["context"]
    if not isinstance(location, dict) or set(location) != {"worktree", "repository", "base", "branch"}:
        raise ValueError("context requires worktree/repository/base/branch")
    if not all(isinstance(v, str) and v for v in location.values()):
        raise ValueError("invalid task context")
    repo = Path(location["worktree"]).expanduser().resolve()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE).strip()
    if git("rev-parse", "--show-toplevel") != str(repo):
        raise ValueError("worktree must be its exact Git root")
    if repository_identity(repo) != location["repository"] or git("branch", "--show-current") != location["branch"]:
        raise ValueError("task repository or branch changed")
    base = git("rev-parse", "--verify", location["base"] + "^{commit}")
    if base != location["base"]:
        raise ValueError("base must be the accepted immutable commit SHA")
    git("merge-base", "--is-ancestor", base, "HEAD")
    return {**location, "worktree": str(repo), "gitDir": git("rev-parse", "--absolute-git-dir"),
            "head": git("rev-parse", "HEAD")}


def prepare(selection: dict, task: dict, references: list[str], explicit: bool) -> dict:
    location = context(task)
    repo = Path(location["worktree"])
    reference = selection.get("reference") if isinstance(selection, dict) else None
    require_current(reference, repo)
    path = Path(reference["path"])
    if path.name != "SKILL.md" or metadata(path) != {key: selection.get(key) for key in ("name", "description", "manualOnly")}:
        raise ValueError("selected Skill metadata does not match its exact reference")
    if selection["manualOnly"] and not explicit:
        raise ValueError("manual-only Skill requires explicit user invocation; catalog acquisition is not invocation")
    return {"protocol": "harness.skill-handoff.v1", "task": task, "context": location,
            "selection": selection, "explicitInvocation": explicit,
            "references": [snapshot(p, repo) for p in references], "trust": "audit-only"}


def load_handoff(record: dict, expected_task: dict, expected_repo: Path) -> dict:
    if not isinstance(record, dict) or record.get("protocol") != "harness.skill-handoff.v1" or record.get("trust") != "audit-only":
        raise ValueError("invalid handoff protocol")
    if record.get("task") != expected_task:
        raise ValueError("handoff does not match the independently supplied accepted task")
    location = context(record["task"])
    if location["worktree"] != str(expected_repo.resolve()):
        raise ValueError("handoff belongs to another execution worktree")
    if location != record.get("context"):
        raise ValueError("handoff task/worktree/HEAD changed; reconcile and prepare a current handoff")
    repo = Path(location["worktree"])
    selection = record["selection"]
    # Reapply manual invocation and metadata validation, not just a caller-supplied digest.
    prepare(selection, record["task"], [], record.get("explicitInvocation") is True)
    for reference in record["references"]:
        require_current(reference, repo)
    return {"handoff": record, "skillBody": Path(selection["reference"]["path"]).read_text(encoding="utf-8"),
            "supportingReferences": record["references"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--runtime", choices=("codex", "pi", "omp", "claude", "opencode"), required=True)
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=int, default=25)
    get = commands.add_parser("get")
    get.add_argument("--selection-file", type=Path, required=True)
    get.add_argument("--explicit-invocation", action="store_true")
    handoff = commands.add_parser("prepare")
    handoff.add_argument("--selection-file", type=Path, required=True)
    handoff.add_argument("--task-file", type=Path, required=True)
    handoff.add_argument("--reference", action="append", default=[])
    handoff.add_argument("--explicit-invocation", action="store_true")
    load = commands.add_parser("load")
    load.add_argument("--handoff-file", type=Path, required=True)
    load.add_argument("--task-file", type=Path, required=True)
    # Always JSON/non-interactive; this flag documents the machine contract.
    for command in (listing, get, handoff, load):
        command.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "list":
            if not 1 <= args.limit <= 200:
                raise ValueError("--limit must be 1..200; narrow --query when truncated")
            result = catalog(args.repo.resolve(), args.runtime, args.query, args.limit)
        elif args.command == "load":
            result = load_handoff(json.loads(args.handoff_file.read_text(encoding="utf-8")),
                                  json.loads(args.task_file.read_text(encoding="utf-8")), args.repo)
        else:
            selection = json.loads(args.selection_file.read_text(encoding="utf-8"))
            if args.command == "prepare":
                result = prepare(selection, json.loads(args.task_file.read_text(encoding="utf-8")), args.reference, args.explicit_invocation)
            else:
                require_current(selection["reference"], args.repo.resolve())
                path = Path(selection["reference"]["path"])
                if path.name != "SKILL.md" or metadata(path) != {k: selection.get(k) for k in ("name", "description", "manualOnly")}:
                    raise ValueError("selected Skill reference/metadata mismatch")
                if selection["manualOnly"] and not args.explicit_invocation:
                    raise ValueError("manual-only Skill body requires explicit user invocation")
                result = {"selection": selection, "body": path.read_text(encoding="utf-8"),
                          "invocation": "explicit-user-only" if selection["manualOnly"] else "parent-selection"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, UnresolvableTarget, subprocess.SubprocessError) as error:
        print(json.dumps({"code": "SKILL_HANDOFF_UNVERIFIED", "reason": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

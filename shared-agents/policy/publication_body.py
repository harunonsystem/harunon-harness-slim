"""Current authored-body/reference evidence for the existing publication gate."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from evidence_files import require_current, snapshot
from repo_target import canonical_repository, repository_identity, UnresolvableTarget


class BodyEvidenceError(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE, timeout=10).strip()


def _read(artifact: str, repo: Path, core: Path, task_id: str, head: str) -> tuple[dict, str, list[dict]]:
    path = Path(artifact).expanduser()
    path = path if path.is_absolute() else repo / path
    data = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"taskId", "subjectSha", "bodyFile", "checks", "target"}:
        raise ValueError("body attestation requires taskId/subjectSha/bodyFile/checks/target")
    if data["taskId"] != task_id or data["subjectSha"] != head:
        raise ValueError("body attestation belongs to another task/HEAD; redo applicable checks")
    body_reference = snapshot(data["bodyFile"], repo)
    body = Path(body_reference["path"]).read_bytes().decode("utf-8")
    if not body.strip() or digest(body) != body_reference["sha256"]:
        raise ValueError("final body is empty or changed while reading")
    checks = data["checks"]
    if not isinstance(checks, dict) or set(checks) != {"rule", "yomiyasu", "showMe"}:
        raise ValueError("record rule read, yomiyasu decision, and show-me decision")
    rule = snapshot(checks["rule"], repo)
    # OpenCode keeps policy below runtime/ and the applied rules one level up.
    rule_path = core / "rules/pr-body.md"
    if not rule_path.is_file():
        rule_path = core.parent / "rules/pr-body.md"
    authoritative = snapshot(rule_path, repo)
    if rule["sha256"] != authoritative["sha256"]:
        raise ValueError("rule must match this kernel's current bundled pr-body rule")
    references = [rule] if rule == authoritative else [rule, authoritative]
    yomi = checks["yomiyasu"]
    mode = yomi.get("mode") if isinstance(yomi, dict) else None
    if mode == "applied":
        if yomi.get("domain") != "business":
            raise ValueError("yomiyasu domain must be business")
        paths = yomi.get("references")
        if not isinstance(paths, list) or not paths or Path(paths[0]).name != "SKILL.md" or Path(paths[0]).parent.name != "yomiyasu":
            raise ValueError("applied yomiyasu requires its exact SKILL.md and applicable references")
        references.extend(snapshot(value, repo) for value in paths)
    elif mode == "english-only":
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", body):
            raise ValueError("English-only omission cannot cover Japanese body text")
    elif mode == "manual-unavailable":
        if yomi.get("unavailable") is not True or not isinstance(yomi.get("reason"), str) or not yomi["reason"].strip():
            raise ValueError("manual fallback requires unavailable runtime and a concrete reason")
    else:
        raise ValueError("yomiyasu mode must be applied, english-only, or manual-unavailable")
    show = checks["showMe"]
    mode = show.get("mode") if isinstance(show, dict) else None
    if mode == "applied":
        paths = show.get("references")
        if not isinstance(paths, list) or not paths or Path(paths[0]).name != "SKILL.md" or Path(paths[0]).parent.name != "show-me" or not isinstance(show.get("format"), str) or not show["format"].strip():
            raise ValueError("show-me requires its exact SKILL.md, references, and selected format")
        references.extend(snapshot(value, repo) for value in paths)
    elif mode == "unnecessary":
        if not isinstance(show.get("reason"), str) or not show["reason"].strip():
            raise ValueError("show-me omission requires a concrete reason")
    else:
        raise ValueError("showMe mode must be applied or unnecessary")
    target = data["target"]
    if not isinstance(target, dict) or target.get("action") not in ("pr.create", "pr.update-body"):
        raise ValueError("target action must be pr.create or pr.update-body")
    if target["action"] == "pr.create":
        if set(target) != {"action"}:
            raise ValueError("create target must not contain a PR number")
    elif set(target) != {"action", "number"} or type(target["number"]) is not int or target["number"] < 1:
        raise ValueError("body-update target requires a positive PR number")
    return {"bodyReference": body_reference, "target": target}, body, references


def _head_ref(repo: Path) -> str:
    branch = _git(repo, "branch", "--show-current")
    upstream = _git(repo, "for-each-ref", "--format=%(upstream:remotename)%09%(upstream:remoteref)", "refs/heads/" + branch)
    if upstream:
        remote, ref = upstream.split("\t")
        if remote == "." or not ref.startswith("refs/heads/"):
            raise ValueError("GitHub upstream branch unavailable")
        branch = ref.removeprefix("refs/heads/")
    if not branch:
        raise ValueError("attached Git branch required")
    return branch


def _remote_body(repo: Path, number: int) -> str:
    identity = repository_identity(repo)
    host, repository = identity.split("/", 1)
    data = json.loads(subprocess.check_output(
        ["gh", "api", "--hostname", host, f"repos/{repository}/pulls/{number}", "--jq",
         "{number,state,body,head:.head.sha,headRef:.head.ref,headRepo:.head.repo.full_name,base:.base.repo.full_name}"],
        cwd=repo, text=True, stderr=subprocess.PIPE, timeout=30))
    if (not isinstance(data, dict) or data.get("number") != number or data.get("state") != "open"
            or data.get("head") != _git(repo, "rev-parse", "HEAD")
            or data.get("headRef") != _head_ref(repo)
            or data.get("base", "").lower() != repository or data.get("headRepo", "").lower() != repository
            or "body" not in data or (data["body"] is not None and not isinstance(data["body"], str))):
        raise ValueError("PR target/head/ref/repository unavailable or different from this worktree")
    return data["body"] or ""


def capture(state: dict, repo: Path, artifact: str, core: Path) -> dict:
    try:
        details, body, references = _read(artifact, repo, core, state["task"]["id"], _git(repo, "rev-parse", "HEAD"))
        target = dict(details["target"])
        if target["action"] == "pr.update-body":
            target["previousBodySha256"] = digest(_remote_body(repo, target["number"]))
            target["headRef"] = _head_ref(repo)
        return {"kind": "publication-body", "trust": "audit-only", "subjectSha": _git(repo, "rev-parse", "HEAD"),
                "publication": {**details, "target": target, "artifactReference": snapshot(artifact, repo),
                                "references": references, "taskId": state["task"]["id"],
                                "repository": repository_identity(repo), "branch": _git(repo, "branch", "--show-current")}}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, UnresolvableTarget, subprocess.SubprocessError) as error:
        raise BodyEvidenceError("PUBLICATION_BODY_INVALID", str(error)) from error


def require(state: dict, repo: Path, request: dict, core: Path) -> None:
    records = [entry for entry in state["evidence"] if entry["kind"] == "publication-body"]
    if not records:
        raise BodyEvidenceError("PUBLICATION_BODY_REQUIRED", "attach-publication-body with the final body and exact rule/Skill references")
    try:
        evidence = records[-1]
        record = evidence["publication"]
        target = record["target"]
        if (evidence["subjectSha"] != _git(repo, "rev-parse", "HEAD") or record["taskId"] != state["task"]["id"]
                or record["repository"] != repository_identity(repo) or record["branch"] != _git(repo, "branch", "--show-current")
                or target["action"] != request["action"]):
            raise ValueError("body evidence task/worktree/HEAD/operation changed")
        for reference in [record["artifactReference"], record["bodyReference"], *record["references"]]:
            require_current(reference, repo)
        # Revalidate declared decisions too. Local attestations cannot certify actual Skill cognition.
        details, body, references = _read(record["artifactReference"]["path"], repo, core, state["task"]["id"], evidence["subjectSha"])
        if details["bodyReference"] != record["bodyReference"] or references != record["references"]:
            raise ValueError("body/Skill references no longer match the attestation")
        if any(target.get(key) != value for key, value in details["target"].items()):
            raise ValueError("publication target differs from the attached artifact")
        payload = request.get("publication")
        if not isinstance(payload, dict) or not isinstance(payload.get("body"), str):
            raise ValueError((payload or {}).get("bodyError", "supported publication needs its actual final body (--body-file), not --fill/stdin/dynamic input"))
        if digest(payload["body"]) != digest(body):
            raise ValueError("actual published body differs from the attached final body")
        if payload.get("repository") is not None and canonical_repository(payload["repository"], selector=True) != record["repository"]:
            raise ValueError("structured publication repository mismatch")
        if payload.get("headBranch") is not None and payload["headBranch"] != record["branch"]:
            raise ValueError("structured publication head branch mismatch")
        if payload.get("headRepository") is not None and canonical_repository(payload["headRepository"], selector=True) != record["repository"]:
            raise ValueError("structured publication head repository mismatch")
        if request["action"] == "pr.update-body":
            if target["headRef"] != _head_ref(repo):
                raise ValueError("publication upstream/head ref changed")
            number = str(payload.get("number", ""))
            if number != str(target["number"]):
                raise ValueError("body update must explicitly select the attached PR number")
            if digest(_remote_body(repo, target["number"])) not in (target["previousBodySha256"], digest(body)):
                raise ValueError("PR body changed after attachment; reconcile before updating")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, UnresolvableTarget, subprocess.SubprocessError) as error:
        raise BodyEvidenceError("PUBLICATION_BODY_STALE", str(error)) from error

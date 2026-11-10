#!/usr/bin/env python3
"""Runtime-neutral workflow state and authorization kernel."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repo_target import (UnresolvableTarget, canonical_repository, gh_target_reason, pr_body_selector, pr_target,
                         repository_identity, resolve_target)
from schema import validate
import verification
import publication_body
import rigor


CORE_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = CORE_DIR / "workflows" / "change.json"
STATE_SCHEMA_FILE = CORE_DIR / "workflows" / "task-state.schema.json"
JsonObject = dict[str, Any]


class KernelError(Exception):
    def __init__(self, code: str, exit_code: int = 3, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code
        self.details = details


def emit(payload: JsonObject, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


def _parse_json_object(raw: str, error_code: str) -> JsonObject:
    """Parse raw JSON text into a dict, raising a uniform KernelError otherwise."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise KernelError(error_code, reason=str(error)) from error
    if not isinstance(value, dict):
        raise KernelError(error_code, reason="expected JSON object")
    return value


def read_request() -> JsonObject:
    try:
        raw = sys.stdin.read()
    except UnicodeDecodeError as error:
        raise KernelError("INVALID_JSON", reason=str(error)) from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise KernelError("INVALID_JSON", reason=str(error)) from error
    if not isinstance(value, dict):
        raise KernelError("INVALID_REQUEST", reason="request must be a JSON object")
    return value


def load_json(path: Path, label: str) -> JsonObject:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise KernelError(f"{label}_INVALID", reason=str(error)) from error
    return _parse_json_object(raw, f"{label}_INVALID")


@dataclass(frozen=True)
class WorkflowContext:
    """The Core Workflow definition and its content hash, loaded once per request."""

    workflow: JsonObject
    version: str


def load_workflow_context() -> WorkflowContext:
    try:
        data = WORKFLOW_FILE.read_bytes()
    except OSError as error:
        raise KernelError("WORKFLOW_INVALID", reason=str(error)) from error
    try:
        workflow = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KernelError("WORKFLOW_INVALID", reason=str(error)) from error
    if not isinstance(workflow, dict):
        raise KernelError("WORKFLOW_INVALID", reason="expected JSON object")
    return WorkflowContext(workflow=workflow, version=hashlib.sha256(data).hexdigest())


def resolve_repo(request: JsonObject) -> Path:
    base = Path(request.get("repo", Path.cwd())).expanduser().resolve()
    command = request.get("command")
    if isinstance(command, str) and command.strip():
        try:
            base = resolve_target(base, command)
        except UnresolvableTarget as error:
            raise KernelError(
                "REPO_TARGET_UNRESOLVABLE", exit_code=2, reason=error.reason
            ) from error
    result = subprocess.run(
        ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KernelError(
            "GIT_CONTEXT_NOT_FOUND",
            cwd=str(base),
            reason=(
                "対象の local worktree を実行 cwd に設定して再実行してください。"
                "gh --repo は GitHub 上の対象指定であり、local Git context は設定しません。"
            ),
        )
    return Path(result.stdout.strip())


def gates_adopted(repo: Path) -> bool:
    """repo 外の registry に remote が載っていれば採用済み。壊れた registry は採用扱いで止める。"""
    try:
        return verification.registry_entry(repo) is not None
    except verification.VerificationError:
        return True


def git_value(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KernelError("GIT_CONTEXT_NOT_FOUND", cwd=str(repo))
    return result.stdout.strip()


def git_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """ancestor が descendant の履歴に含まれるか（同一 commit も真）。

    レビュー証跡は「レビューした commit R が現在の HEAD の祖先」なら有効とみなす。
    レビュー後の修正 commit（policy: 指摘は全件修正、再レビューはしない）で HEAD が
    進むのは想定どおりで、ブランチ作り直しなど R が履歴から消えた場合だけ stale。
    block-repeated-codex-review.sh の done flag と同じ判定。
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def resolve_state_file(explicit: Path | None, repo: Path) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return Path(git_value(repo, "--absolute-git-dir")) / "harness" / "v2" / "state.json"


def validate_state(state: JsonObject) -> None:
    schema = load_json(STATE_SCHEMA_FILE, "STATE_SCHEMA")
    errors = validate(state, schema)
    if errors:
        raise KernelError("STATE_INVALID", errors=errors)


def read_state(path: Path) -> JsonObject:
    if not path.is_file():
        raise KernelError("STATE_NOT_FOUND", exit_code=2, path=str(path))
    state = load_json(path, "STATE")
    try:
        validate_state(state)
    except KernelError:
        # 旧 workflow で書かれた state は schema ごと古い（廃止した phase・assignments 等）。
        # schema 違反ではなく version 違いとして返し、start で置き換えられるようにする。
        workflow = state.get("workflow") if isinstance(state, dict) else None
        stored = workflow.get("version") if isinstance(workflow, dict) else None
        current = load_workflow_context().version
        if isinstance(stored, str) and stored != current:
            raise KernelError("WORKFLOW_VERSION_MISMATCH", stored=stored, current=current) from None
        raise
    return state


def assert_workflow_bound(state: JsonObject, ctx: WorkflowContext) -> None:
    """Raise unless state was written against the currently-loaded workflow definition."""
    if state["workflow"]["version"] != ctx.version:
        raise KernelError(
            "WORKFLOW_VERSION_MISMATCH",
            stored=state["workflow"]["version"],
            current=ctx.version,
        )


def write_state(path: Path, state: JsonObject) -> None:
    validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".state-",
            delete=False,
        ) as output:
            json.dump(state, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def state_lock(path: Path):
    """Serialize state mutations and authorization across agent processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def validate_context(state: JsonObject, repo: Path) -> None:
    expected = state["context"]
    actual = {
        "gitDir": git_value(repo, "--absolute-git-dir"),
        "worktreeRoot": str(repo),
    }
    if expected != actual:
        raise KernelError(
            "STATE_CONTEXT_MISMATCH",
            stored=expected,
            current=actual,
        )


def initial_state(request: JsonObject, repo: Path, ctx: WorkflowContext) -> JsonObject:
    workflow = ctx.workflow
    task_id = request.get("taskId")
    state = {
        "schemaVersion": 2,
        "revision": 0,
        "phase": workflow["initialState"],
        "task": {"id": task_id},
        "workflow": {"name": workflow["name"], "version": ctx.version},
        "context": {
            "gitDir": git_value(repo, "--absolute-git-dir"),
            "worktreeRoot": str(repo),
        },
        "evidence": [],
        "reviewAttempts": 0,
    }
    return state


def check_revision(state: JsonObject, request: JsonObject) -> None:
    expected = request.get("expectedRevision")
    if expected != state["revision"]:
        raise KernelError(
            "REVISION_CONFLICT",
            exit_code=2,
            expectedRevision=expected,
            actualRevision=state["revision"],
        )


def validate_review_evidence(evidence: JsonObject, repo: Path) -> None:
    """Verify evidence.provider/artifact reference a real, readable review output.

    Only kind/trust/subjectSha were checked before this, so any caller could
    attach fabricated local-review evidence by copying those fields verbatim
    and pointing artifact at a path that never existed (M-003). CLI adapters
    (run-change's harness.py, codex_review.py) already resolve and verify the
    artifact before calling the kernel; this closes the same gap for callers
    that bypass the adapter (e.g. the OpenCode native tool), which forwarded
    args straight to the kernel unverified.
    """
    provider = evidence.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise KernelError(
            "INVALID_REVIEW_EVIDENCE",
            reason="provider must be a non-empty string",
        )
    artifact = evidence.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        raise KernelError(
            "INVALID_REVIEW_EVIDENCE",
            reason="artifact must be a non-empty string",
        )
    check_artifact_exists(artifact, repo)


def check_artifact_exists(artifact: str, repo: Path) -> None:
    """Verify an evidence artifact path is real and readable.

    Used by local-review evidence (validate_review_evidence): the artifact must be a
    verified file rather than a reviewer's self-reported path.
    """
    artifact_path = Path(artifact).expanduser()
    if artifact_path.is_absolute():
        # Absolute artifacts are not required to live inside the repo tree:
        # codex_review.py stores review output under the git directory, which
        # for a linked worktree (git worktree add) resolves outside the
        # worktree root by design. Existence + readability below is the gate.
        resolved = artifact_path.resolve()
    else:
        # Repo-relative artifacts must resolve inside the repo; reject
        # traversal that escapes the repo root (e.g. "../../etc/passwd").
        resolved = (repo / artifact_path).resolve()
        try:
            resolved.relative_to(repo.resolve())
        except ValueError as error:
            raise KernelError(
                "REVIEW_ARTIFACT_OUTSIDE_REPO",
                exit_code=2,
                artifact=artifact,
            ) from error
    # Empty files are accepted: the existing run-change adapter (attach-review)
    # only checks Path.is_file(), never file size, so a zero-byte artifact was
    # already valid evidence before this fix. Matching that keeps the kernel
    # check a strict superset of the adapter's, rather than a stricter one.
    if not resolved.is_file() or not os.access(resolved, os.R_OK):
        raise KernelError(
            "REVIEW_ARTIFACT_NOT_FOUND",
            exit_code=2,
            artifact=artifact,
        )


def task_is_active(state: JsonObject) -> bool:
    """Protect progressed tasks from task.start overwrite; never bypass authorization."""
    return state["phase"] != "complete" and state["revision"] > 0


def independent_review_required(repo: Path) -> bool:
    """Classify the whole branch and checkout using the existing router exemptions.

    Unresolvable bases, empty diffs and ambiguous path transport fail closed.
    --no-renames retains a deleted code path when it is renamed to a document.
    """
    try:
        default = subprocess.run(
            ["git", "-C", str(repo), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        candidates = [default] if default else []
        candidates += ["refs/remotes/origin/main", "refs/heads/main", "refs/remotes/origin/master", "refs/heads/master"]
        base = None
        for candidate in candidates:
            result = subprocess.run(["git", "-C", str(repo), "merge-base", candidate, "HEAD"], capture_output=True, text=True)
            if result.returncode == 0:
                base = result.stdout.strip()
                break
        if base is None:
            return True
        paths = set()
        for args in (("diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--"),
                     ("diff", "--name-only", "--no-renames", "-z", base, "--"),
                     ("diff", "--cached", "--name-only", "--no-renames", "-z", base, "--"),
                     ("ls-files", "--others", "--exclude-standard", "-z")):
            paths.update(os.fsdecode(path) for path in verification.git(repo, *args).split(b"\0") if path)
        if any("\n" in path or "\t" in path or "\r" in path for path in paths):
            return True
        # Revert exemption only applies to a clean branch, never to added work.
        subjects = "" if verification.git(repo, "status", "--porcelain") else verification.git(repo, "log", "--format=%s", f"{base}..HEAD").decode()
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; review_route 0 "$2"', "review-route", str(Path(__file__).with_name("review-router.sh")), subjects],
            cwd=repo, input="".join(f"M\t{path}\n" for path in sorted(paths)), capture_output=True, text=True,
        )
        return result.returncode != 0 or result.stdout.strip() not in ("none", "bypass")
    except (OSError, UnicodeError, verification.VerificationError):
        return True


def _apply_review_report(
    state: JsonObject,
    request: JsonObject,
    repo: Path,
    workflow: JsonObject,
) -> None:
    """local-review evidence を検証して decide に進める（review.attach の本体）。"""
    evidence = request.get("evidence")
    self_check = isinstance(evidence, dict) and evidence.get("provider") == "self-check"
    quota_self_check = (
        state["phase"] == "publish"
        and self_check
        and any(entry["kind"] == "review-skipped" for entry in state["evidence"])
    )
    first_independent = (
        not self_check and state["reviewAttempts"] == 0
        and state["phase"] in ("decide", "publish")
        and any(entry["kind"] == "local-review" and entry.get("provider") == "self-check" for entry in state["evidence"])
        and not any(entry["kind"] == "review-skipped" for entry in state["evidence"])
    )
    if state["phase"] != "review" and not (self_check and state["phase"] in ("decide", "publish")) and not first_independent:
        raise KernelError("INVALID_REVIEW_PHASE", exit_code=2, phase=state["phase"])
    approval = state.get("rereviewApproval")
    if not self_check and state["reviewAttempts"] >= 1 and approval is None:
        raise KernelError(
            "REVIEW_LIMIT_REACHED",
            exit_code=2,
            reviewAttempts=state["reviewAttempts"],
        )
    if not isinstance(evidence, dict):
        raise KernelError("INVALID_REVIEW_EVIDENCE")
    expected = {
        "kind": "local-review",
        "trust": "audit-only",
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise KernelError(
            "INVALID_REVIEW_EVIDENCE",
            reason="local review evidence must be explicitly audit-only",
        )
    validate_review_evidence(evidence, repo)
    if evidence.get("subjectSha") != git_value(repo, "HEAD"):
        raise KernelError("REVIEW_SUBJECT_STALE", exit_code=2)
    if self_check:
        state["evidence"].append(evidence)
        if quota_self_check or (state["phase"] == "review" and not independent_review_required(repo)):
            state["phase"] = workflow["states"]["review"]["review_attached"]
        return
    if approval is not None:
        evidence["rereviewReason"] = approval["reason"]
        state.pop("rereviewApproval")
    state["evidence"].append(evidence)
    state["reviewAttempts"] += 1
    state["phase"] = workflow["states"]["review"]["review_attached"]


def _apply_review_skip(
    state: JsonObject,
    request: JsonObject,
    repo: Path,
    workflow: JsonObject,
) -> None:
    """quota 切れで review が返らなかった事実を evidence に記録し、publish へ進める。

    rules/codex-review-policy.md の「quota 切れは SKIP」を Core Workflow 側に写した
    もの。legacy flag（codex-review-bypass.sh --quota）だけだと active な task では
    PR gate が kernel に委譲して review phase で止まり続ける。skipReason は quota
    のみ（接続・認証・companion のクラッシュは止まってユーザーに確認する契約なので
    kernel に SKIP 経路を持たせない）。
    """
    if state["phase"] != "review":
        raise KernelError("INVALID_REVIEW_PHASE", exit_code=2, phase=state["phase"])
    evidence = request.get("evidence")
    if not isinstance(evidence, dict):
        raise KernelError("INVALID_REVIEW_EVIDENCE")
    expected = {"kind": "review-skipped", "trust": "audit-only", "skipReason": "quota"}
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise KernelError(
            "INVALID_REVIEW_EVIDENCE",
            reason="review skip evidence must be kind review-skipped, audit-only, skipReason quota",
        )
    reason = evidence.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise KernelError("REVIEW_SKIP_REASON_REQUIRED", exit_code=2)
    provider = evidence.get("provider")
    if provider is not None and (not isinstance(provider, str) or not provider.strip()):
        raise KernelError("INVALID_REVIEW_EVIDENCE", reason="provider must be a non-empty string")
    # subjectSha は呼び出し元の自己申告ではなく kernel が HEAD を記録する
    evidence["subjectSha"] = git_value(repo, "HEAD")
    state["evidence"].append(evidence)
    state["phase"] = workflow["states"]["review"]["review_skipped"]


def apply_event(state_file: Path, repo: Path, request: JsonObject, ctx: WorkflowContext) -> JsonObject:
    event_type = request.get("type")
    if event_type == "task.start":
        if state_file.exists():
            # 非アクティブ判定は workflow version を bind せずに行う。change.json 更新後に
            # 残った state は phase を問わずもう進められないので、VERSION_MISMATCH で
            # start まで拒むと gate も解除できない永続ブロックになる。旧 workflow の state は
            # schema ごと古い（旧 phase / assignments）ので read_state が VERSION_MISMATCH を返す。
            try:
                existing = read_state(state_file)
            except KernelError as error:
                if error.code != "WORKFLOW_VERSION_MISMATCH":
                    raise
                # 旧 schema の state でも、別 repo / worktree のものは置き換えない
                stale = load_json(state_file, "STATE")
                if isinstance(stale.get("context"), dict):
                    validate_context(stale, repo)
                existing = None
            if existing is not None:
                validate_context(existing, repo)
            if existing is not None and task_is_active(existing) and existing["workflow"]["version"] == ctx.version:
                raise KernelError(
                    "ACTIVE_TASK_EXISTS",
                    exit_code=2,
                    phase=existing["phase"],
                    taskId=existing["task"]["id"],
                )
        state = initial_state(request, repo, ctx)
        write_state(state_file, state)
        return state

    known_events = {
        "verification.run",
        "task.complete",
        "phase.advance",
        "review.attach",
        "review.approve",
        "review.skip",
        "publication.attach",
    }
    if event_type not in known_events:
        raise KernelError("UNKNOWN_EVENT", eventType=event_type)

    state = read_state(state_file)
    assert_workflow_bound(state, ctx)
    validate_context(state, repo)
    check_revision(state, request)
    workflow = ctx.workflow

    if event_type == "task.complete" or (event_type == "phase.advance" and request.get("event") == "published" and state["phase"] == "publish"):
        verification.require_current(state["evidence"], repo)
        decision = review_decision(state, repo, ctx)
        if not decision["allowed"]:
            raise KernelError(decision["code"], exit_code=2, reason="complete pre-review-check, required independent review and the decision before finishing")
        if event_type != "task.complete":
            publication_body.require(state, repo, {**request, "action": "pr.create"}, CORE_DIR)
    if event_type == "task.complete":
        state["phase"] = "complete"
    elif event_type == "verification.run":
        # 検証は phase を進めない。どの phase でも最新の証跡を記録し直せる
        if state["phase"] not in workflow["states"]:
            raise KernelError("INVALID_VERIFICATION_PHASE", exit_code=2, phase=state["phase"])
        # Persist an unsuccessful attempt before execution. A killed kernel must
        # never leave an earlier passing receipt usable after a failed rerun.
        state["evidence"].append({"kind": "verification", "trust": "audit-only", "passed": False})
        state["revision"] += 1
        write_state(state_file, state)
        state["evidence"][-1] = verification.run(repo, state_file.parent / "verification")
    elif event_type == "phase.advance":
        event = request.get("event")
        transitions = workflow["states"].get(state["phase"])
        if not isinstance(transitions, dict):
            raise KernelError("STATE_INVALID", errors=["$.phase: unknown workflow phase"])
        if event not in transitions:
            raise KernelError(
                "INVALID_TRANSITION",
                exit_code=2,
                phase=state["phase"],
                event=event,
            )
        if event in ("review_attached", "review_skipped"):
            # evidence 付きイベント（review.attach / review.skip）だけが通せる遷移
            raise KernelError("PROTECTED_TRANSITION", exit_code=2, event=event)
        state["phase"] = transitions[event]
    elif event_type == "review.approve":
        if state["phase"] != "review" or state["reviewAttempts"] < 1:
            raise KernelError("INVALID_REREVIEW_APPROVAL_PHASE", exit_code=2)
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise KernelError("REREVIEW_REASON_REQUIRED", exit_code=2)
        state["rereviewApproval"] = {"reason": reason.strip()}
    elif event_type == "review.skip":
        _apply_review_skip(state, request, repo, workflow)
    elif event_type == "review.attach":
        _apply_review_report(state, request, repo, workflow)
    else:
        assert event_type == "publication.attach"
        if state["phase"] not in ("review", "decide", "publish", "complete"):
            raise KernelError("INVALID_PUBLICATION_PHASE", exit_code=2, phase=state["phase"])
        artifact = request.get("artifact")
        if not isinstance(artifact, str) or not artifact.strip():
            raise KernelError("PUBLICATION_ARTIFACT_REQUIRED", exit_code=2)
        state["evidence"].append(publication_body.capture(state, repo, artifact, CORE_DIR))
    state["revision"] += 1
    write_state(state_file, state)
    return state


def review_decision(state: JsonObject, repo: Path, ctx: WorkflowContext) -> JsonObject:
    """Shared completion/publication readiness, without authorizing network egress."""
    if state["phase"] not in ctx.workflow["actions"]["pr.create"]["allowedStates"]:
        return {"allowed": False, "code": "WORKFLOW_NOT_READY", "phase": state["phase"]}
    head = git_value(repo, "HEAD")
    # Both checks cover remediation descendants; quota SKIP never replaces a self-check.
    code = None
    self_check = False
    independent = False
    for evidence in state["evidence"]:
        if evidence["kind"] not in ("local-review", "review-skipped"):
            continue
        subject = evidence.get("subjectSha")
        if not isinstance(subject, str):
            continue
        if subject != head and not git_is_ancestor(repo, subject, head):
            continue
        if evidence["kind"] == "local-review":
            code = "LOCAL_REVIEW_CURRENT" if subject == head else code or "LOCAL_REVIEW_ANCESTOR"
            self_check |= evidence.get("provider") == "self-check"
            independent |= bool(evidence.get("provider")) and evidence["provider"] != "self-check"
        elif evidence.get("skipReason") == "quota" and evidence.get("provider") != "self-check":
            independent = True
    if code is None:
        return {"allowed": False, "code": "REVIEW_STALE"}
    if not self_check:
        return {"allowed": False, "code": "PRE_REVIEW_CHECK_REQUIRED"}
    if not independent and independent_review_required(repo):
        return {"allowed": False, "code": "INDEPENDENT_REVIEW_REQUIRED"}
    return {"allowed": True, "code": code, "trust": "audit-only"}


def check_pr_create_target(repo: Path, request: JsonObject) -> None:
    command = request.get("command")
    reason = gh_target_reason(
        command if isinstance(command, str) and command.strip() else "gh pr create",
        git_value(repo, "--abbrev-ref", "HEAD"), repo,
    )
    if reason is not None:
        raise KernelError("REPO_TARGET_UNRESOLVABLE", exit_code=2, reason=reason)


_SHELL_EXPANSION = "$`{}*?[]~"
_PR_URL = re.compile(r"https://([\w.-]+)/([\w.-]+)/([\w.-]+)/pull/[1-9][0-9]*/?", re.IGNORECASE)


def check_casual_publication_target(repo: Path, request: JsonObject) -> None:
    """casual skips the body evidence, so pin here what it pinned: this checkout's repo and branch."""
    identity = repository_identity(repo)

    def deny(reason: str) -> None:
        raise KernelError("REPO_TARGET_UNRESOLVABLE", exit_code=2, reason=reason)

    def same_repository(value: Any) -> bool:
        try:
            return isinstance(value, str) and canonical_repository(value, selector=True) == identity
        except UnresolvableTarget:
            return False

    command = request.get("command")
    if isinstance(command, str) and command.strip():
        check_pr_create_target(repo, request)  # -R / GH_REPO / GH_HOST / --head
        # The tokenizers drop quote context, so substitution, brace, glob or tilde expansion could
        # add arguments or run a second, unchecked command. Refuse them anywhere in the command.
        if any(char in command for char in _SHELL_EXPANSION):
            deny("展開文字（$ ` { } * ? [ ] ~）を含む command は通せません（本文は --body-file で渡してください）")
        if request.get("action") == "pr.create":
            return
        # gh pr edit / comment take a positional PR selector that may name another repo: allow
        # only none (current branch), a bare number, or a URL of this checkout's repo.
        try:
            selector = pr_body_selector(command)
        except UnresolvableTarget as error:
            deny(error.reason)
        if selector is None or re.fullmatch(r"[1-9][0-9]*", selector):
            return
        match = _PR_URL.fullmatch(selector)
        if not match or not same_repository(f"https://{match[1]}/{match[2]}/{match[3]}"):
            deny("PR の指定は番号か、この checkout の repo の PR URL にしてください")
        return
    # MCP requests carry no command, so their structured fields must name this checkout.
    publication = request.get("publication")
    if not isinstance(publication, dict) or not same_repository(publication.get("repository")):
        deny("公開先の repo が checkout と一致しません")
    if publication.get("headRepository") is not None and not same_repository(publication["headRepository"]):
        deny("head の repo が checkout と一致しません")
    if request.get("action") == "pr.create" and publication.get("headBranch") != git_value(repo, "--abbrev-ref", "HEAD"):
        deny("作成する PR の head branch が現在の branch と一致しません")


def casual_repository(repo: Path) -> bool:
    """The checkout's own remote decides; `-R` to any other repo is rejected by the target checks."""
    try:
        return rigor.is_casual_repository(repository_identity(repo))
    except UnresolvableTarget:
        return False


def gh_pr_view(repository: str, number: str) -> JsonObject:
    try:
        result = subprocess.run(
            ["gh", "pr", "view", number, "--repo", repository, "--json", "state,headRefOid,statusCheckRollup"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KernelError("CASUAL_MERGE_PR_UNREADABLE", exit_code=2, reason=str(error)) from error
    if result.returncode != 0:
        raise KernelError("CASUAL_MERGE_PR_UNREADABLE", exit_code=2, reason=result.stderr.strip()[:500])
    return _parse_json_object(result.stdout, "CASUAL_MERGE_PR_UNREADABLE")


def _check_passed(check: Any) -> bool:
    if not isinstance(check, dict):
        return False
    if "state" in check:  # StatusContext
        return check["state"] == "SUCCESS"
    return check.get("status") == "COMPLETED" and check.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED")


# approve-pr.sh の承認ではこの境界を越えられない。拒否だけ返すと人が main へ直接 push する
# 迂回に流れた（2026-11-04）ので、通る手順を返す。
TRUSTED_REVIEW_NEXT = (
    "この repo の merge は GitHub の required check と branch protection が判定します"
    "（approve-pr.sh やローカルの証跡では通せないので、承認を取り直しても変わりません）。"
    "checks の通過後に、ユーザーが GitHub の UI か自分の terminal で merge してください"
)


def casual_merge_decision(repo: Path, request: JsonObject) -> JsonObject:
    """Authorize the pinned remote PR head using GitHub checks, not local checkout evidence."""
    command = request.get("command")
    publication = request.get("publication")
    try:
        if isinstance(command, str) and command.strip():
            target = pr_target(repo, command)
            if target["operation"] != "pr.merge":
                raise UnresolvableTarget("merge 以外の PR 操作です")
            repository, number = target["repository"], target["number"]
            expected_head = target.get("matchHeadCommit")
        elif isinstance(publication, dict) and isinstance(publication.get("repository"), str):
            repository = canonical_repository(publication["repository"], selector=True)
            number = str(publication.get("number", ""))
            expected_head = publication.get("headSha")
            if repository != repository_identity(repo) or not number.isdigit() or number.startswith("0"):
                raise UnresolvableTarget("merge 対象の repo / PR 番号が checkout と一致しません")
        else:
            raise UnresolvableTarget("merge 対象の PR 番号を確定できません")
    except UnresolvableTarget as error:
        return {"allowed": False, "code": "REPO_TARGET_UNRESOLVABLE", "reason": error.reason}
    if not rigor.is_casual_repository(repository):
        return {"allowed": False, "code": "TRUSTED_REVIEW_REQUIRED", "reason": TRUSTED_REVIEW_NEXT}
    if not isinstance(expected_head, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        return {"allowed": False, "code": "CASUAL_MERGE_HEAD_REQUIRED",
                "reason": "gh pr view で headRefOid を確認し、gh pr merge に --match-head-commit <SHA> を指定してください。"
                          "merge だけならローカル task・worktree・verify は不要です"}
    pr = gh_pr_view(repository, number)
    checks = pr.get("statusCheckRollup")
    state = pr.get("state")
    if state != "OPEN":
        next_step = ("merge 済みなので操作は不要です" if state == "MERGED"
                     else "閉じた PR を merge するかは、reopen するかを含めてユーザーが判断してください")
        return {"allowed": False, "code": "CASUAL_MERGE_PR_NOT_OPEN",
                "reason": f"PR #{number} は {state or '状態不明'} です。{next_step}"}
    if pr.get("headRefOid") != expected_head:
        return {"allowed": False, "code": "CASUAL_MERGE_HEAD_MISMATCH",
                "reason": f"PR の head（{pr.get('headRefOid') or '不明'}）が、指定した SHA（{expected_head}）と違います。"
                          "新しい head の差分と checks を確認してから、その SHA を指定してください"}
    if not isinstance(checks, list) or not all(_check_passed(check) for check in checks):
        failed = isinstance(checks, list) and any(check.get("conclusion") == "FAILURE" or check.get("state") == "FAILURE"
                                                  for check in checks if isinstance(check, dict))
        next_step = ("失敗した check を直して push してください" if failed
                     else f"`gh pr checks {number}` で完了を待ってから merge してください")
        return {"allowed": False, "code": "CASUAL_MERGE_CHECKS_NOT_PASSED",
                "reason": f"PR #{number} の checks が成功していません。{next_step}"}
    if not checks:
        return {"allowed": False, "code": "CASUAL_MERGE_CHECKS_NOT_PASSED",
                "reason": f"PR #{number} に checks が 1 つもありません。CI を足すか、ユーザーが自分で merge してください"}
    return {"allowed": True, "code": "CASUAL_MERGE_VERIFIED"}


def authorize(state_file: Path, repo: Path, request: JsonObject, ctx: WorkflowContext) -> JsonObject:
    action = request.get("action")
    workflow = ctx.workflow
    action_policy = workflow.get("actions", {}).get(action)
    if not isinstance(action_policy, dict):
        raise KernelError("UNKNOWN_ACTION", exit_code=2, action=action)
    # A merge acts on a remote PR, not this checkout. GitHub checks and the pinned
    # head protect casual merges even without a local task, including adopted repos.
    if action == "pr.merge" and casual_repository(repo):
        return {"action": action, **casual_merge_decision(repo, request)}
    # registry に載った repo だけが gate を採用する。repo 側にファイルは置かせない。
    if not gates_adopted(repo):
        if action == "pr.create":
            check_pr_create_target(repo, request)
        return {"action": action, "allowed": True, "code": "NOT_ADOPTED"}
    # Missing tasks and tasks from an older workflow version must re-enter the gate,
    # never fall back to legacy flags. Current completed tasks still need fresh verification.
    try:
        state = read_state(state_file)
    except KernelError as error:
        if error.code in ("STATE_NOT_FOUND", "WORKFLOW_VERSION_MISMATCH"):
            raise KernelError("TASK_REQUIRED", exit_code=2, reason="start and verify before completing or publishing") from error
        raise
    validate_context(state, repo)
    if state["workflow"]["version"] != ctx.version:
        raise KernelError(
            "TASK_REQUIRED",
            exit_code=2,
            phase=state["phase"],
            revision=state["revision"],
            taskId=state["task"]["id"],
        )
    state = read_state(state_file)
    assert_workflow_bound(state, ctx)
    casual = action != "task.report" and casual_repository(repo)
    # casual publication needs no review evidence, so it may start from the review phase.
    allowed_states = [*action_policy["allowedStates"], *(("review", "decide") if casual else ())]
    if state["phase"] not in allowed_states:
        return {
            "action": action,
            "allowed": False,
            "code": "WORKFLOW_NOT_READY",
            "phase": state["phase"],
        }
    verification.require_current(state["evidence"], repo)
    if action == "task.report":
        decision = review_decision(state, repo, ctx)
        if decision["allowed"]:
            decision["code"] = "TASK_COMPLETE_CURRENT"
        return {"action": action, **decision}
    if casual and action in ("pr.create", "pr.update-body", "pr.comment"):
        # casual: current verification is the only publication requirement (ADR-009 addendum).
        check_casual_publication_target(repo, request)
        return {"action": action, "allowed": True, "code": "CASUAL_VERIFIED"}
    if action == "pr.comment":
        return {"action": action, **review_decision(state, repo, ctx)}
    if action in ("pr.create", "pr.update-body"):
        check_pr_create_target(repo, request)
        decision = review_decision(state, repo, ctx)
        if decision["allowed"]:
            publication_body.require(state, repo, request, CORE_DIR)
        return {"action": action, **decision}
    # Outside casual targets, merge is the external enforcement boundary. Local files
    # remain audit-only and can never satisfy the required GitHub status check.
    return {
        "action": action,
        "allowed": False,
        "code": "TRUSTED_REVIEW_REQUIRED",
        "reason": TRUSTED_REVIEW_NEXT,
    }


SUPPORTED_OPERATIONS = (
    "inspect",
    "verify",
    "complete",
    "start",
    "advance",
    "approve_review",
    "attach_review",
    "attach_publication_body",
    "skip_review",
    "authorize",
)


def _operation_error(code: str, operation: Any, **details: Any) -> KernelError:
    return KernelError(code, operation=operation, **details)


def _operation_arguments(operation: Any, arguments: Any) -> JsonObject:
    if not isinstance(operation, str) or not operation:
        raise _operation_error("INVALID_OPERATION", operation)
    if operation not in SUPPORTED_OPERATIONS:
        raise _operation_error("UNKNOWN_OPERATION", operation)
    if not isinstance(arguments, dict):
        raise _operation_error(
            "INVALID_OPERATION_ARGUMENTS",
            operation,
            reason="arguments must be a JSON object",
        )
    return arguments


def _validate_operation_keys(
    operation: str,
    arguments: JsonObject,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    allowed = set(required) | set(optional)
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        raise _operation_error(
            "OPERATION_ARGUMENT_UNEXPECTED",
            operation,
            arguments=unexpected,
        )
    for name in required:
        if name not in arguments:
            raise _operation_error(
                "OPERATION_ARGUMENT_REQUIRED",
                operation,
                argument=name,
            )


def _operation_string(operation: str, arguments: JsonObject, name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str) or not value.strip():
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason="must be a non-empty string",
        )
    return value


def _operation_revision(operation: str, arguments: JsonObject) -> int:
    value = arguments["expectedRevision"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument="expectedRevision",
            reason="must be a non-negative integer",
        )
    return value


def _operation_json_object(operation: str, arguments: JsonObject, name: str) -> JsonObject:
    raw = arguments[name]
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason="must be a JSON object",
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason=str(error),
        ) from error
    if not isinstance(value, dict):
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason="must be a JSON object",
        )
    return value


def _operation_artifact(operation: str, arguments: JsonObject, name: str) -> str:
    return str(Path(_operation_string(operation, arguments, name)).expanduser())


def _resolve_operation_artifact(artifact: str, repo: Path) -> str:
    path = Path(artifact)
    return str(path.resolve() if path.is_absolute() else (repo / path).resolve())


def compile_operation(
    operation: Any,
    arguments: Any,
    repo: Path,
) -> tuple[str, JsonObject]:
    operation_arguments = _operation_arguments(operation, arguments)
    assert isinstance(operation, str)
    if operation == "inspect":
        _validate_operation_keys(operation, operation_arguments, ())
        return "inspect", {}
    if operation == "start":
        _validate_operation_keys(operation, operation_arguments, ("taskId",))
        return "apply", {"type": "task.start", "taskId": _operation_string(operation, operation_arguments, "taskId")}
    if operation == "advance":
        _validate_operation_keys(operation, operation_arguments, ("event", "expectedRevision"), ("publication",))
        return "apply", {
            "type": "phase.advance",
            "event": _operation_string(operation, operation_arguments, "event"),
            "expectedRevision": _operation_revision(operation, operation_arguments),
            **({"publication": _operation_json_object(operation, operation_arguments, "publication")} if "publication" in operation_arguments else {}),
        }
    if operation in ("verify", "complete"):
        _validate_operation_keys(operation, operation_arguments, ("expectedRevision",))
        return "apply", {"type": "verification.run" if operation == "verify" else "task.complete", "expectedRevision": _operation_revision(operation, operation_arguments)}
    if operation == "approve_review":
        _validate_operation_keys(operation, operation_arguments, ("reason", "expectedRevision"))
        return "apply", {
            "type": "review.approve",
            "reason": _operation_string(operation, operation_arguments, "reason"),
            "expectedRevision": _operation_revision(operation, operation_arguments),
        }
    if operation == "attach_review":
        _validate_operation_keys(
            operation,
            operation_arguments,
            ("expectedRevision", "provider", "subjectSha", "artifact"),
        )
        artifact = _operation_artifact(operation, operation_arguments, "artifact")
        check_artifact_exists(artifact, repo)
        artifact = _resolve_operation_artifact(artifact, repo)
        return "apply", {
            "type": "review.attach",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "evidence": {
                "kind": "local-review",
                "trust": "audit-only",
                "provider": _operation_string(operation, operation_arguments, "provider"),
                "subjectSha": _operation_string(operation, operation_arguments, "subjectSha"),
                "artifact": artifact,
            },
        }
    if operation == "attach_publication_body":
        _validate_operation_keys(operation, operation_arguments, ("expectedRevision", "artifact"))
        return "apply", {"type": "publication.attach", "expectedRevision": _operation_revision(operation, operation_arguments),
                         "artifact": _resolve_operation_artifact(_operation_artifact(operation, operation_arguments, "artifact"), repo)}
    if operation == "skip_review":
        _validate_operation_keys(operation, operation_arguments, ("expectedRevision", "provider", "reason"))
        return "apply", {
            "type": "review.skip",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "evidence": {
                "kind": "review-skipped",
                "trust": "audit-only",
                "provider": _operation_string(operation, operation_arguments, "provider"),
                "skipReason": "quota",
                "reason": _operation_string(operation, operation_arguments, "reason"),
            },
        }
    _validate_operation_keys(operation, operation_arguments, ("action",), ("publication", "command"))
    return "authorize", {"action": _operation_string(operation, operation_arguments, "action"),
                         **({"publication": _operation_json_object(operation, operation_arguments, "publication")} if "publication" in operation_arguments else {}),
                         **({"command": _operation_string(operation, operation_arguments, "command")} if "command" in operation_arguments else {})}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "apply", "authorize", "operate"):
        commands.add_parser(name)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        request = read_request()
        repo = resolve_repo(request)
        state_file = resolve_state_file(args.state_file, repo)
        ctx = load_workflow_context()
        command = args.command
        if command == "operate":
            command, request = compile_operation(
                request.get("operation"),
                request.get("arguments"),
                repo,
            )
        if command == "inspect":
            state = read_state(state_file)
            assert_workflow_bound(state, ctx)
            validate_context(state, repo)
            return emit({"state": state})
        if command == "apply":
            with state_lock(state_file):
                state = apply_event(state_file, repo, request, ctx)
                validate_context(state, repo)
            if request.get("type") == "verification.run" and not state["evidence"][-1]["passed"]:
                return emit({"code": "VERIFICATION_FAILED", "state": state}, 2)
            return emit({"state": state})
        with state_lock(state_file):
            decision = authorize(state_file, repo, request, ctx)
            return emit(decision, 0 if decision["allowed"] else 2)


    except KernelError as error:
        return emit({"code": error.code, **error.details}, error.exit_code)
    except verification.VerificationError as error:
        return emit({"code": "VERIFICATION_REQUIRED", "reason": str(error)}, 2)
    except publication_body.BodyEvidenceError as error:
        return emit({"code": error.code, "reason": str(error)}, 2)
    except (KeyError, TypeError, ValueError) as error:
        return emit({"code": "INTERNAL_CONTRACT_VIOLATION", "reason": str(error)}, 3)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Runtime-neutral workflow state and authorization kernel."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repo_target import UnresolvableTarget, gh_target_reason, resolve_target
from schema import validate
import verification


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
        raise KernelError("GIT_CONTEXT_NOT_FOUND", cwd=str(base))
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
    validate_state(state)
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
    mode = request.get("mode", "change")
    phase = workflow["entryStates"].get(mode)
    if phase is None:
        raise KernelError("INVALID_TASK_MODE", mode=mode)
    state = {
        "schemaVersion": 2,
        "revision": 0,
        "phase": phase,
        "task": {"id": task_id},
        "workflow": {"name": workflow["name"], "version": ctx.version},
        "context": {
            "gitDir": git_value(repo, "--absolute-git-dir"),
            "worktreeRoot": str(repo),
        },
        "evidence": [],
        "reviewAttempts": 0,
        "assignments": [],
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

    Shared by local-review evidence (validate_review_evidence) and worker-report
    evidence (assignment.report, implement role) — both point at a coordinator-
    verified file rather than trusting a worker's self-reported path.
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


def _apply_review_report(
    state: JsonObject,
    request: JsonObject,
    repo: Path,
    workflow: JsonObject,
    assignment_index: int | None,
) -> None:
    """local-review evidence を検証して decide に進める。review.attach と
    assignment.report(role=review) の共通本体（ADR-012 §2 の別名維持）。
    assignment_index が None なら assignment 側の記帳はしない（assignment を
    使わない従来の review.attach 呼び出し）。
    """
    evidence = request.get("evidence")
    quota_self_check = (
        state["phase"] == "publish"
        and isinstance(evidence, dict)
        and evidence.get("provider") == "self-check"
        and any(entry["kind"] == "review-skipped" for entry in state["evidence"])
    )
    if state["phase"] != "review" and not quota_self_check:
        raise KernelError("INVALID_REVIEW_PHASE", exit_code=2, phase=state["phase"])
    approval = state.get("rereviewApproval")
    if state["reviewAttempts"] >= 1 and approval is None:
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
    if approval is not None:
        evidence["rereviewReason"] = approval["reason"]
        state.pop("rereviewApproval")
    if assignment_index is not None:
        evidence["assignmentIndex"] = assignment_index
    state["evidence"].append(evidence)
    state["reviewAttempts"] += 1
    state["phase"] = workflow["states"]["review"]["review_attached"]
    if assignment_index is not None:
        state["assignments"][assignment_index]["status"] = "reported"


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


def _apply_implement_report(
    state: JsonObject,
    request: JsonObject,
    repo: Path,
    assignment_index: int,
) -> None:
    """worker-report evidence を検証して implement assignment を reported にする。

    変更ファイル一覧は worker の自己申告を信じない（ADR-012 §1）ので、ここで
    確認するのは「その HEAD が本当にそこにあるか」（resultSha）と「割当時の
    base から実際に進んだか」（subjectSha が祖先か）だけに絞る。
    """
    evidence = request.get("evidence")
    if not isinstance(evidence, dict):
        raise KernelError("INVALID_REVIEW_EVIDENCE")
    expected = {"kind": "worker-report", "trust": "audit-only"}
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise KernelError(
            "INVALID_REVIEW_EVIDENCE",
            reason="worker report evidence must be kind worker-report and audit-only",
        )
    for field in ("executor", "workerId", "resultSha", "artifact"):
        value = evidence.get(field)
        if not isinstance(value, str) or not value.strip():
            raise KernelError(
                "INVALID_REVIEW_EVIDENCE",
                reason=f"{field} must be a non-empty string",
            )
    # subjectSha は割当時に kernel が記録した値を使う。worker の自己申告に
    # base を差し替えられると祖先チェックの意味が無くなるため、evidence の値では
    # なく assignments[assignment_index] を真実として扱う（ADR-012 §1）。
    evidence["subjectSha"] = state["assignments"][assignment_index]["subjectSha"]
    checks = evidence.get("checks", [])
    if not isinstance(checks, list):
        raise KernelError("INVALID_REVIEW_EVIDENCE", reason="checks must be an array")
    for check in checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("command"), str)
            or not check["command"].strip()
            or not isinstance(check.get("exitCode"), int)
            or isinstance(check.get("exitCode"), bool)
        ):
            raise KernelError(
                "INVALID_REVIEW_EVIDENCE",
                reason="each check needs a non-empty command and an integer exitCode",
            )
    check_artifact_exists(evidence["artifact"], repo)
    head = git_value(repo, "HEAD")
    if evidence["resultSha"] != head:
        raise KernelError("REPORT_SUBJECT_STALE", exit_code=2)
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            evidence["subjectSha"],
            evidence["resultSha"],
        ],
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise KernelError("REPORT_BASE_NOT_ANCESTOR", exit_code=2)
    evidence["assignmentIndex"] = assignment_index
    state["evidence"].append(evidence)
    state["assignments"][assignment_index]["status"] = "reported"
    state["assignments"][assignment_index]["resultSha"] = evidence["resultSha"]


def apply_event(state_file: Path, repo: Path, request: JsonObject, ctx: WorkflowContext) -> JsonObject:
    event_type = request.get("type")
    if event_type == "task.start":
        if state_file.exists():
            # 非アクティブ判定は workflow version を bind せずに行う。change.json 更新後に
            # 残った complete / 着手前 state を VERSION_MISMATCH で読めなくすると、
            # 新タスクを start できず gate も解除できない永続ブロックに戻るため。
            existing = read_state(state_file)
            validate_context(existing, repo)
            if task_is_active(existing):
                assert_workflow_bound(existing, ctx)
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
        "assignment.create",
        "assignment.dispatched",
        "assignment.report",
        "assignment.abandon",
    }
    if event_type not in known_events:
        raise KernelError("UNKNOWN_EVENT", eventType=event_type)

    state = read_state(state_file)
    assert_workflow_bound(state, ctx)
    validate_context(state, repo)
    check_revision(state, request)
    workflow = ctx.workflow
    assignments = state["assignments"]

    if event_type == "task.complete" or (event_type == "phase.advance" and request.get("event") == "published" and state["phase"] == "publish"):
        verification.require_current(state["evidence"], repo)
        decision = self_check_decision(state, repo, ctx)
        if not decision["allowed"]:
            raise KernelError(decision["code"], exit_code=2, reason="complete the mandatory self-check and decision before finishing")
    if event_type == "task.complete":
        state["phase"] = "complete"
    elif event_type == "verification.run":
        if state["phase"] not in ("verify", "checkpoint", "review", "decide", "publish", "complete"):
            raise KernelError("INVALID_VERIFICATION_PHASE", exit_code=2, phase=state["phase"])
        # Persist an unsuccessful attempt before execution. A killed kernel must
        # never leave an earlier passing receipt usable after a failed rerun.
        state["evidence"].append({"kind": "verification", "trust": "audit-only", "passed": False})
        state["revision"] += 1
        write_state(state_file, state)
        state["evidence"][-1] = verification.run(repo, state_file.parent / "verification")
        if state["evidence"][-1]["passed"] and state["phase"] == "verify":
            state["phase"] = workflow["states"]["verify"]["checks_passed"]
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
        if event in ("review_attached", "review_skipped", "checks_passed"):
            # evidence 付きイベント（review.attach / review.skip）だけが通せる遷移
            raise KernelError("PROTECTED_TRANSITION", exit_code=2, event=event)
        if event == "implemented" and assignments and assignments[-1]["role"] == "implement":
            # dispatched のまま先に進む経路だけを塞ぐ。assignment を使わない
            # 直接実装（casual タスク、委譲コストが上回る軽微修正）は従来どおり通す。
            if assignments[-1]["status"] != "reported":
                raise KernelError(
                    "ASSIGNMENT_NOT_REPORTED",
                    exit_code=2,
                    status=assignments[-1]["status"],
                )
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
        # 現在の assignment が review/dispatched なら assignment.report(role=review)
        # の別名として振る舞う。それ以外（assignment 無し、または他 role/status）は
        # 従来どおり assignment に触れない review.attach として扱う（後方互換）。
        current = assignments[-1] if assignments else None
        assignment_index = (
            len(assignments) - 1
            if current is not None
            and current["role"] == "review"
            and current["status"] in ("assigned", "dispatched")
            else None
        )
        _apply_review_report(state, request, repo, workflow, assignment_index)
    elif event_type == "assignment.create":
        if state["phase"] not in ("implement", "review"):
            raise KernelError("INVALID_ASSIGNMENT_PHASE", exit_code=2, phase=state["phase"])
        role = request.get("role")
        if role not in ("implement", "review"):
            raise KernelError("INVALID_ASSIGNMENT_ROLE", exit_code=2, role=role)
        if role != state["phase"]:
            # ADR-012 §2 の「phase が implement または review」は role ごとの
            # その phase を指す（implement role は implement phase だけ、review
            # role は review phase だけ）。組み合わせの自由度を持たせない。
            raise KernelError(
                "ASSIGNMENT_ROLE_PHASE_MISMATCH",
                exit_code=2,
                role=role,
                phase=state["phase"],
            )
        executor = request.get("executor")
        worker_id = request.get("workerId")
        if not isinstance(executor, str) or not executor.strip():
            raise KernelError("ASSIGNMENT_FIELD_REQUIRED", exit_code=2, field="executor")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise KernelError("ASSIGNMENT_FIELD_REQUIRED", exit_code=2, field="workerId")
        current = assignments[-1] if assignments else None
        if current is not None and current["status"] not in ("reported", "abandoned"):
            raise KernelError("ASSIGNMENT_ACTIVE", exit_code=2, status=current["status"])
        assignments.append(
            {
                "role": role,
                "executor": executor,
                "workerId": worker_id,
                "status": "assigned",
                "correlationId": uuid.uuid4().hex,
                "subjectSha": git_value(repo, "HEAD"),
            }
        )
    elif event_type == "assignment.dispatched":
        if not assignments or assignments[-1]["status"] != "assigned":
            raise KernelError(
                "INVALID_ASSIGNMENT_STATUS",
                exit_code=2,
                status=assignments[-1]["status"] if assignments else None,
            )
        transport = request.get("transport")
        ref = request.get("ref")
        at = request.get("at")
        if not isinstance(transport, str) or not transport.strip():
            raise KernelError("ASSIGNMENT_FIELD_REQUIRED", exit_code=2, field="transport")
        if not isinstance(ref, dict):
            raise KernelError("ASSIGNMENT_FIELD_REQUIRED", exit_code=2, field="ref")
        if not isinstance(at, str) or not at.strip():
            raise KernelError("ASSIGNMENT_FIELD_REQUIRED", exit_code=2, field="at")
        assignments[-1]["status"] = "dispatched"
        assignments[-1]["dispatch"] = {"transport": transport, "ref": ref, "at": at}
    elif event_type == "assignment.report":
        if not assignments or assignments[-1]["status"] != "dispatched":
            raise KernelError(
                "INVALID_ASSIGNMENT_STATUS",
                exit_code=2,
                status=assignments[-1]["status"] if assignments else None,
            )
        assignment_index = len(assignments) - 1
        if assignments[assignment_index]["role"] == "review":
            _apply_review_report(state, request, repo, workflow, assignment_index)
        else:
            _apply_implement_report(state, request, repo, assignment_index)
    else:
        assert event_type == "assignment.abandon"
        if not assignments or assignments[-1]["status"] not in ("assigned", "dispatched"):
            raise KernelError(
                "INVALID_ASSIGNMENT_STATUS",
                exit_code=2,
                status=assignments[-1]["status"] if assignments else None,
            )
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise KernelError("ABANDON_REASON_REQUIRED", exit_code=2)
        assignments[-1]["status"] = "abandoned"
        assignments[-1]["abandonReason"] = reason.strip()

    state["revision"] += 1
    write_state(state_file, state)
    return state


def self_check_decision(state: JsonObject, repo: Path, ctx: WorkflowContext) -> JsonObject:
    """Shared completion/publication readiness, without authorizing network egress."""
    if state["phase"] not in ctx.workflow["actions"]["pr.create"]["allowedStates"]:
        return {"allowed": False, "code": "WORKFLOW_NOT_READY", "phase": state["phase"]}
    head = git_value(repo, "HEAD")
    # Review covers its commit and remediation descendants; quota SKIP is not a self-check.
    code = None
    for evidence in state["evidence"]:
        if evidence["kind"] != "local-review":
            continue
        subject = evidence.get("subjectSha")
        if not isinstance(subject, str):
            continue
        if subject == head:
            code = "LOCAL_REVIEW_CURRENT"
            break
        if git_is_ancestor(repo, subject, head):
            code = "LOCAL_REVIEW_ANCESTOR"
    if code is not None:
        return {"allowed": True, "code": code, "trust": "audit-only"}
    return {"allowed": False, "code": "REVIEW_STALE"}


def check_pr_create_target(repo: Path, request: JsonObject) -> None:
    command = request.get("command")
    reason = gh_target_reason(
        command if isinstance(command, str) and command.strip() else "gh pr create",
        git_value(repo, "--abbrev-ref", "HEAD"), repo,
    )
    if reason is not None:
        raise KernelError("REPO_TARGET_UNRESOLVABLE", exit_code=2, reason=reason)


def authorize(state_file: Path, repo: Path, request: JsonObject, ctx: WorkflowContext) -> JsonObject:
    action = request.get("action")
    workflow = ctx.workflow
    action_policy = workflow.get("actions", {}).get(action)
    if not isinstance(action_policy, dict):
        raise KernelError("UNKNOWN_ACTION", exit_code=2, action=action)
    # registry に載った repo だけが gate を採用する。repo 側にファイルは置かせない。
    if not gates_adopted(repo):
        if action == "pr.create":
            check_pr_create_target(repo, request)
        return {"action": action, "allowed": True, "code": "NOT_ADOPTED"}
    # Missing/stale completed tasks must re-enter the gate, never fall back to
    # legacy flags. Current completed tasks still need fresh verification.
    try:
        state = read_state(state_file)
    except KernelError as error:
        if error.code == "STATE_NOT_FOUND":
            raise KernelError("TASK_REQUIRED", exit_code=2, reason="start --publish-only and verify before completing or publishing") from error
        raise
    validate_context(state, repo)
    if state["phase"] == "complete" and state["workflow"]["version"] != ctx.version:
        raise KernelError(
            "TASK_REQUIRED",
            exit_code=2,
            phase=state["phase"],
            revision=state["revision"],
            taskId=state["task"]["id"],
        )
    state = read_state(state_file)
    assert_workflow_bound(state, ctx)
    if state["phase"] not in action_policy["allowedStates"]:
        return {
            "action": action,
            "allowed": False,
            "code": "WORKFLOW_NOT_READY",
            "phase": state["phase"],
        }
    verification.require_current(state["evidence"], repo)
    if action == "task.report":
        # complete already required the self-check; reporting needs it to stay verified.
        return {"action": action, "allowed": True, "code": "TASK_COMPLETE_CURRENT"}
    if action == "pr.create":
        check_pr_create_target(repo, request)
        return {"action": action, **self_check_decision(state, repo, ctx)}
    # Merge is the external enforcement boundary. Local files remain audit-only
    # and can never satisfy the required GitHub status check.
    return {
        "action": action,
        "allowed": False,
        "code": "TRUSTED_REVIEW_REQUIRED",
    }


SUPPORTED_OPERATIONS = (
    "inspect",
    "verify",
    "complete",
    "start",
    "advance",
    "approve_review",
    "attach_review",
    "skip_review",
    "assign",
    "dispatched",
    "report",
    "abandon",
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


def _operation_json_array(operation: str, arguments: JsonObject, name: str) -> list[Any]:
    raw = arguments[name]
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason="must be a JSON array",
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
    if not isinstance(value, list):
        raise _operation_error(
            "OPERATION_ARGUMENT_INVALID",
            operation,
            argument=name,
            reason="must be a JSON array",
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
        _validate_operation_keys(operation, operation_arguments, ("taskId",), ("mode",))
        task_id = _operation_string(operation, operation_arguments, "taskId")
        request: JsonObject = {"type": "task.start", "taskId": task_id}
        if "mode" in operation_arguments:
            mode = _operation_string(operation, operation_arguments, "mode")
            if mode not in ("change", "publish"):
                raise _operation_error(
                    "OPERATION_ARGUMENT_INVALID",
                    operation,
                    argument="mode",
                    reason="must be change or publish",
                )
            request["mode"] = mode
        return "apply", request
    if operation == "advance":
        _validate_operation_keys(operation, operation_arguments, ("event", "expectedRevision"))
        return "apply", {
            "type": "phase.advance",
            "event": _operation_string(operation, operation_arguments, "event"),
            "expectedRevision": _operation_revision(operation, operation_arguments),
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
    if operation == "assign":
        _validate_operation_keys(
            operation,
            operation_arguments,
            ("expectedRevision", "role", "executor", "workerId"),
        )
        role = _operation_string(operation, operation_arguments, "role")
        if role not in ("implement", "review"):
            raise _operation_error(
                "OPERATION_ARGUMENT_INVALID",
                operation,
                argument="role",
                reason="must be implement or review",
            )
        return "apply", {
            "type": "assignment.create",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "role": role,
            "executor": _operation_string(operation, operation_arguments, "executor"),
            "workerId": _operation_string(operation, operation_arguments, "workerId"),
        }
    if operation == "dispatched":
        _validate_operation_keys(
            operation,
            operation_arguments,
            ("expectedRevision", "transport", "ref", "at"),
        )
        return "apply", {
            "type": "assignment.dispatched",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "transport": _operation_string(operation, operation_arguments, "transport"),
            "ref": _operation_json_object(operation, operation_arguments, "ref"),
            "at": _operation_string(operation, operation_arguments, "at"),
        }
    if operation == "report":
        _validate_operation_keys(
            operation,
            operation_arguments,
            ("expectedRevision", "executor", "workerId", "resultSha", "artifact"),
            ("checks",),
        )
        artifact = _operation_artifact(operation, operation_arguments, "artifact")
        check_artifact_exists(artifact, repo)
        artifact = _resolve_operation_artifact(artifact, repo)
        checks = (
            _operation_json_array(operation, operation_arguments, "checks")
            if "checks" in operation_arguments
            else []
        )
        return "apply", {
            "type": "assignment.report",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "evidence": {
                "kind": "worker-report",
                "trust": "audit-only",
                "executor": _operation_string(operation, operation_arguments, "executor"),
                "workerId": _operation_string(operation, operation_arguments, "workerId"),
                "resultSha": _operation_string(operation, operation_arguments, "resultSha"),
                "artifact": artifact,
                "checks": checks,
            },
        }
    if operation == "abandon":
        _validate_operation_keys(operation, operation_arguments, ("expectedRevision", "reason"))
        return "apply", {
            "type": "assignment.abandon",
            "expectedRevision": _operation_revision(operation, operation_arguments),
            "reason": _operation_string(operation, operation_arguments, "reason"),
        }
    _validate_operation_keys(operation, operation_arguments, ("action",))
    return "authorize", {"action": _operation_string(operation, operation_arguments, "action")}


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
    except (KeyError, TypeError, ValueError) as error:
        return emit({"code": "INTERNAL_CONTRACT_VIOLATION", "reason": str(error)}, 3)


if __name__ == "__main__":
    raise SystemExit(main())

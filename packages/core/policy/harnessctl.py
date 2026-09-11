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


def git_value(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KernelError("GIT_CONTEXT_NOT_FOUND", cwd=str(repo))
    return result.stdout.strip()


def resolve_state_file(explicit: Path | None, repo: Path) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return Path(git_value(repo, "--absolute-git-dir")) / "harness" / "state.json"


def validate_state(state: JsonObject) -> None:
    schema = load_json(STATE_SCHEMA_FILE, "STATE_SCHEMA")
    errors = validate(state, schema)
    if errors:
        raise KernelError("STATE_INVALID", errors=errors)


def _validate_v1_minimal(state: JsonObject) -> list[str]:
    """schemaVersion 1 の state を task_is_active 判定に必要な最小限だけ検証する。

    v1 の state は v2 スキーマ（assignments 必須等）を満たさないため、フルスキーマ
    validate は必ず失敗する。task_is_active が使うフィールドだけ確認すれば、非
    アクティブな旧 state を安全に読める（ADR-012 §6）。
    """
    errors: list[str] = []
    if not isinstance(state.get("phase"), str):
        errors.append("$.phase: missing or invalid")
    if not isinstance(state.get("revision"), int) or isinstance(state.get("revision"), bool):
        errors.append("$.revision: missing or invalid")
    task = state.get("task")
    if not isinstance(task, dict) or not isinstance(task.get("id"), str):
        errors.append("$.task.id: missing or invalid")
    if not isinstance(state.get("context"), dict):
        errors.append("$.context: missing or invalid")
    return errors


def read_state(path: Path) -> JsonObject:
    if not path.is_file():
        raise KernelError("STATE_NOT_FOUND", exit_code=2, path=str(path))
    state = load_json(path, "STATE")
    if state.get("schemaVersion") == 1:
        # 非アクティブな v1 state だけ読める（task.start での上書き、authorize の
        # inactive 判定）。active な v1 state はここで必ず止め、旧 kernel で完了
        # させる（永続ブロックを作らない既存原則は「非アクティブなら必ず解除
        # できる」ことを指すので、active な旧 state を騙し騙し進めるのは対象外）。
        errors = _validate_v1_minimal(state)
        if errors:
            raise KernelError("STATE_INVALID", errors=errors)
        if task_is_active(state):
            raise KernelError("STATE_SCHEMA_VERSION_UNSUPPORTED", exit_code=2)
        return state
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
    """Serialize compare-and-swap mutations across agent processes."""
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
    """Core Workflow の gate と task.start の保護対象になるタスクか。

    state.json は complete 後も削除されないし、task.start 直後（revision 0）は
    何も記録されていない。この両者を「進行中」と扱うと、同じ checkout からの
    PR 作成が誰にも解除できない形で永続ブロックされる（2026-08-26 に 7/13 起票の
    intake 放置タスクと、8/16 に complete した旧タスクの両方で実測。OpenCode は
    rigor profile による casual スキップを持たないため毎回顕在化した）。
    progress のあるタスクだけを進行中とみなす。
    """
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
    if state["phase"] != "review":
        raise KernelError("INVALID_REVIEW_PHASE", exit_code=2, phase=state["phase"])
    approval = state.get("rereviewApproval")
    if state["reviewAttempts"] >= 1 and approval is None:
        raise KernelError(
            "REVIEW_LIMIT_REACHED",
            exit_code=2,
            reviewAttempts=state["reviewAttempts"],
        )
    evidence = request.get("evidence")
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
            # v1 state は read_state 内で active なら STATE_SCHEMA_VERSION_UNSUPPORTED
            # になり、非アクティブなら素通しされる（ADR-012 §6）。
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
        "phase.advance",
        "review.attach",
        "review.approve",
        "assignment.create",
        "assignment.dispatched",
        "assignment.report",
        "assignment.abandon",
    }
    if event_type not in known_events:
        raise KernelError("UNKNOWN_EVENT", eventType=event_type)

    state = read_state(state_file)
    if state.get("schemaVersion") != 2:
        # read_state は非アクティブな v1 state をそのまま返す（task.start の上書き
        # 判定用）。task.start 以外のイベントは v2 の assignments 等を前提にする
        # ため、ここで v1 を弾かないと state["assignments"] で KeyError になり
        # INTERNAL_CONTRACT_VIOLATION（exit 3）に化けてしまう。
        raise KernelError("STATE_SCHEMA_VERSION_UNSUPPORTED", exit_code=2)
    assert_workflow_bound(state, ctx)
    validate_context(state, repo)
    check_revision(state, request)
    workflow = ctx.workflow
    assignments = state["assignments"]

    if event_type == "phase.advance":
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
        if event == "review_attached":
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


def authorize(state_file: Path, repo: Path, request: JsonObject, ctx: WorkflowContext) -> JsonObject:
    action = request.get("action")
    workflow = ctx.workflow
    action_policy = workflow.get("actions", {}).get(action)
    if not isinstance(action_policy, dict):
        raise KernelError("UNKNOWN_ACTION", exit_code=2, action=action)
    # 進行中タスクが無い checkout は STATE_NOT_FOUND と同じ扱い（adapter 側で素通し）。
    # 個別コードにするのは、adapter が「未開始」と「終了済み」を区別してログに残せるようにするため。
    # 判定は workflow version を bind せずに行う（task.start と同じ理由: 旧 change.json で
    # 書かれた complete state が VERSION_MISMATCH になると永続ブロックに戻る）。
    state = read_state(state_file)
    validate_context(state, repo)
    if not task_is_active(state):
        raise KernelError(
            "WORKFLOW_INACTIVE",
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
    if action == "pr.create":
        command = request.get("command")
        if isinstance(command, str) and command.strip():
            current_branch = git_value(repo, "--abbrev-ref", "HEAD")
            reason = gh_target_reason(command, current_branch)
            if reason is not None:
                raise KernelError("REPO_TARGET_UNRESOLVABLE", exit_code=2, reason=reason)
        head = git_value(repo, "HEAD")
        current = any(
            evidence["kind"] == "local-review"
            and evidence["subjectSha"] == head
            for evidence in state["evidence"]
        )
        if current:
            return {
                "action": action,
                "allowed": True,
                "code": "LOCAL_REVIEW_CURRENT",
                "trust": "audit-only",
            }
        return {"action": action, "allowed": False, "code": "REVIEW_STALE"}
    # Merge is the external enforcement boundary. Local files remain audit-only
    # and can never satisfy the required GitHub status check.
    return {
        "action": action,
        "allowed": False,
        "code": "TRUSTED_REVIEW_REQUIRED",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "apply", "authorize"):
        commands.add_parser(name)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        request = read_request()
        repo = resolve_repo(request)
        state_file = resolve_state_file(args.state_file, repo)
        ctx = load_workflow_context()
        if args.command == "inspect":
            state = read_state(state_file)
            if state.get("schemaVersion") != 2:
                raise KernelError("STATE_SCHEMA_VERSION_UNSUPPORTED", exit_code=2)
            assert_workflow_bound(state, ctx)
            validate_context(state, repo)
            return emit({"state": state})
        if args.command == "apply":
            with state_lock(state_file):
                state = apply_event(state_file, repo, request, ctx)
                validate_context(state, repo)
            return emit({"state": state})
        decision = authorize(state_file, repo, request, ctx)
        return emit(decision, 0 if decision["allowed"] else 2)
    except KernelError as error:
        return emit({"code": error.code, **error.details}, error.exit_code)
    except (KeyError, TypeError, ValueError) as error:
        return emit({"code": "INTERNAL_CONTRACT_VIOLATION", "reason": str(error)}, 3)


if __name__ == "__main__":
    raise SystemExit(main())

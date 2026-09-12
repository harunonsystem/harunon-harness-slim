#!/usr/bin/env python3
"""Runtime-neutral workflow kernel public CLI contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESSCTL = REPO_ROOT / "packages" / "core" / "policy" / "harnessctl.py"
WORKFLOW = REPO_ROOT / "packages" / "core" / "workflows" / "change.json"


class HarnessctlTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.repo / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "initial"],
            check=True,
        )
        self.state_file = self.root / "state.json"
        self.artifact = self.root / "review.txt"
        self.artifact.write_text("looks fine\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, command: str, request: dict | str) -> subprocess.CompletedProcess[str]:
        body = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run(
            [
                sys.executable,
                str(HARNESSCTL),
                "--state-file",
                str(self.state_file),
                command,
            ],
            input=body,
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertTrue(result.stdout, msg=result.stderr)
        return json.loads(result.stdout)

    def start(self, task: str = "HAR-123") -> dict:
        result = self.run_cli("apply", {"type": "task.start", "taskId": task})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return self.payload(result)["state"]

    def advance(self, state: dict, event: str) -> dict:
        result = self.run_cli(
            "apply",
            {
                "type": "phase.advance",
                "event": event,
                "expectedRevision": state["revision"],
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return self.payload(result)["state"]

    def to_review(self) -> dict:
        state = self.start()
        for event in (
            "requirements_clear",
            "isolated",
            "planned",
            "implemented",
            "checks_passed",
            "committed",
        ):
            state = self.advance(state, event)
        return state

    def to_implement(self) -> dict:
        state = self.start()
        for event in ("requirements_clear", "isolated", "planned"):
            state = self.advance(state, event)
        return state

    def head(self) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit_file(self, name: str, content: str) -> None:
        (self.repo / name).write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", name], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", f"add {name}"],
            check=True,
        )


class TestThreeEntryInterface(HarnessctlTestCase):
    def test_apply_start_then_inspect_uses_json_protocol_and_versioned_state(self) -> None:
        started = self.start()

        inspected = self.run_cli("inspect", {})

        self.assertEqual(inspected.returncode, 0, msg=inspected.stdout + inspected.stderr)
        self.assertEqual(self.payload(inspected)["state"], started)
        self.assertEqual(started["schemaVersion"], 2)
        self.assertEqual(started["revision"], 0)
        self.assertEqual(started["phase"], "intake")
        self.assertEqual(started["task"]["id"], "HAR-123")
        self.assertEqual(started["workflow"]["name"], "change")
        self.assertEqual(len(started["workflow"]["version"]), 64)

    def test_only_three_public_entry_points_exist(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HARNESSCTL), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("{inspect,apply,authorize}", result.stdout)
        for removed in ("transition", "review", "guard-shell", "check"):
            self.assertNotIn(removed, result.stdout)


class TestStateContract(HarnessctlTestCase):
    def test_apply_uses_revision_compare_and_swap(self) -> None:
        state = self.start()
        first = self.advance(state, "requirements_clear")

        stale = self.run_cli(
            "apply",
            {
                "type": "phase.advance",
                "event": "requirements_clear",
                "expectedRevision": state["revision"],
            },
        )

        self.assertEqual(stale.returncode, 2)
        self.assertEqual(self.payload(stale)["code"], "REVISION_CONFLICT")
        self.assertEqual(self.payload(self.run_cli("inspect", {}))["state"], first)

    def test_corrupt_or_unknown_state_fails_closed(self) -> None:
        self.state_file.write_text('{"schemaVersion":1,"surprise":true}\n', encoding="utf-8")

        result = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(result.returncode, 3)
        payload = self.payload(result)
        self.assertEqual(payload["code"], "STATE_INVALID")
        self.assertTrue(payload["errors"])

    def test_malformed_state_json_fails_closed(self) -> None:
        self.state_file.write_text("{broken\n", encoding="utf-8")

        result = self.run_cli("inspect", {})

        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.payload(result)["code"], "STATE_INVALID")

    def test_workflow_version_mismatch_fails_closed(self) -> None:
        state = self.start()
        state["workflow"]["version"] = "0" * 64
        self.state_file.write_text(json.dumps(state) + "\n", encoding="utf-8")

        result = self.run_cli("inspect", {})

        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.payload(result)["code"], "WORKFLOW_VERSION_MISMATCH")

    def test_state_cannot_be_reused_from_another_repository(self) -> None:
        self.start()
        other = self.root / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True)

        result = subprocess.run(
            [
                sys.executable,
                str(HARNESSCTL),
                "--state-file",
                str(self.state_file),
                "inspect",
            ],
            input="{}",
            cwd=other,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["code"], "STATE_CONTEXT_MISMATCH")

    def test_write_validation_rejects_empty_task_without_creating_state(self) -> None:
        result = self.run_cli("apply", {"type": "task.start", "taskId": ""})

        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.payload(result)["code"], "STATE_INVALID")
        self.assertFalse(self.state_file.exists())


class TestReviewEvidence(HarnessctlTestCase):
    def test_local_review_is_recorded_as_audit_only_without_running_a_cli(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "any-runtime",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        updated = self.payload(result)["state"]
        self.assertEqual(updated["phase"], "decide")
        self.assertEqual(updated["evidence"][0]["trust"], "audit-only")

    def test_local_review_allows_pr_creation_but_is_reported_as_audit_only(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        attached = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )
        state = self.payload(attached)["state"]
        state = self.advance(state, "accepted")

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 0)
        self.assertEqual(
            self.payload(decision),
            {
                "action": "pr.create",
                "allowed": True,
                "code": "LOCAL_REVIEW_CURRENT",
                "trust": "audit-only",
            },
        )

    def test_merge_authorization_requires_an_external_trusted_check(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        attached = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )
        state = self.advance(self.payload(attached)["state"], "accepted")

        decision = self.run_cli("authorize", {"action": "pr.merge"})

        self.assertEqual(decision.returncode, 2)
        self.assertEqual(self.payload(decision)["code"], "TRUSTED_REVIEW_REQUIRED")

    def test_second_review_requires_recorded_user_approval(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        def attach(current: dict) -> subprocess.CompletedProcess[str]:
            return self.run_cli(
                "apply",
                {
                    "type": "review.attach",
                    "expectedRevision": current["revision"],
                    "evidence": {
                        "kind": "local-review",
                        "trust": "audit-only",
                        "provider": "codex",
                        "subjectSha": head,
                        "artifact": str(self.artifact),
                    },
                },
            )

        first = self.payload(attach(state))["state"]
        state = self.advance(first, "fix_selected")
        for event in ("implemented", "checks_passed", "committed"):
            state = self.advance(state, event)

        denied = attach(state)
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(self.payload(denied)["code"], "REVIEW_LIMIT_REACHED")

        approved = self.run_cli(
            "apply",
            {
                "type": "review.approve",
                "expectedRevision": state["revision"],
                "reason": "user requested a final review",
            },
        )
        approved_state = self.payload(approved)["state"]
        second = attach(approved_state)
        self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
        evidence = self.payload(second)["state"]["evidence"][-1]
        self.assertEqual(evidence["rereviewReason"], "user requested a final review")

    def test_review_attach_rejects_a_blank_provider(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "  ",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.payload(result)["code"], "INVALID_REVIEW_EVIDENCE")

    def test_review_attach_rejects_an_artifact_that_does_not_exist(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": str(self.root / "no-such-review.txt"),
                },
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "REVIEW_ARTIFACT_NOT_FOUND")

    def test_review_attach_rejects_a_relative_artifact_that_escapes_the_repo(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        outside = self.root / "outside.txt"
        outside.write_text("not a real review\n", encoding="utf-8")

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": "../outside.txt",
                },
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "REVIEW_ARTIFACT_OUTSIDE_REPO")

    def test_review_attach_accepts_a_repo_relative_artifact(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (self.repo / "review.txt").write_text("looks fine\n", encoding="utf-8")

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": "review.txt",
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["state"]["phase"], "decide")


class TestTaskStartSupersedesUntouchedTask(HarnessctlTestCase):
    """task.start が既存タスクを守るのは progress（revision > 0）があるときだけ。

    intake のまま放置された revision 0 の state を ACTIVE 扱いにすると、同じ
    checkout からの PR 作成が誰にも解除できない形で永続ブロックされる
    （2026-08-26 に 7/13 起票の放置タスクで実測）。
    """

    def test_start_over_untouched_intake_task_replaces_it(self) -> None:
        self.start("STALE-1")

        result = self.run_cli("apply", {"type": "task.start", "taskId": "FRESH-2"})

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["task"]["id"], "FRESH-2")
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["phase"], "intake")

    def test_start_over_task_with_progress_is_rejected(self) -> None:
        state = self.start("BUSY-1")
        self.advance(state, "requirements_clear")

        result = self.run_cli("apply", {"type": "task.start", "taskId": "FRESH-2"})

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        payload = self.payload(result)
        self.assertEqual(payload["code"], "ACTIVE_TASK_EXISTS")
        self.assertEqual(payload["taskId"], "BUSY-1")
        self.assertEqual(payload["phase"], "isolate")


class TestAuthorizeIgnoresInactiveTask(HarnessctlTestCase):
    """authorize は進行中タスクが無い state を STATE_NOT_FOUND 相当（WORKFLOW_INACTIVE）で返す。

    complete 後も state.json は残るため、旧タスク終了後の同じ checkout で pr.create が
    WORKFLOW_NOT_READY(phase=complete) として永続ブロックされていた（2026-08-26 に
    OpenCode で実測。Claude は rigor casual で gate ごと skip していたので気付かなかった）。
    """

    def _head(self) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _complete(self) -> dict:
        state = self.to_review()
        attached = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": self._head(),
                    "artifact": str(self.artifact),
                },
            },
        )
        state = self.payload(attached)["state"]
        state = self.advance(state, "accepted")
        return self.advance(state, "published")

    def test_completed_task_does_not_gate_pr_create(self) -> None:
        state = self._complete()
        self.assertEqual(state["phase"], "complete")

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 2, msg=decision.stdout + decision.stderr)
        payload = self.payload(decision)
        self.assertEqual(payload["code"], "WORKFLOW_INACTIVE")
        self.assertEqual(payload["phase"], "complete")
        self.assertEqual(payload["taskId"], "HAR-123")

    def test_untouched_intake_task_does_not_gate_pr_create(self) -> None:
        self.start("STALE-1")

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 2, msg=decision.stdout + decision.stderr)
        payload = self.payload(decision)
        self.assertEqual(payload["code"], "WORKFLOW_INACTIVE")
        self.assertEqual(payload["revision"], 0)

    def test_completed_task_from_older_workflow_version_is_still_inactive(self) -> None:
        """change.json 更新後に残った complete state は VERSION_MISMATCH ではなく
        WORKFLOW_INACTIVE として扱い、新タスクの start も通す（Codex review 指摘）。"""
        self._complete()
        stale = json.loads(self.state_file.read_text(encoding="utf-8"))
        stale["workflow"]["version"] = "0" * 64
        self.state_file.write_text(json.dumps(stale), encoding="utf-8")

        decision = self.run_cli("authorize", {"action": "pr.create"})
        self.assertEqual(self.payload(decision)["code"], "WORKFLOW_INACTIVE")

        started = self.run_cli("apply", {"type": "task.start", "taskId": "FRESH-2"})
        self.assertEqual(started.returncode, 0, msg=started.stdout + started.stderr)
        self.assertEqual(self.payload(started)["state"]["task"]["id"], "FRESH-2")

    def test_task_with_progress_is_still_gated(self) -> None:
        state = self.start("BUSY-1")
        self.advance(state, "requirements_clear")

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 2, msg=decision.stdout + decision.stderr)
        payload = self.payload(decision)
        self.assertEqual(payload["code"], "WORKFLOW_NOT_READY")
        self.assertEqual(payload["phase"], "isolate")


class TestFailClosedProtocol(HarnessctlTestCase):
    def test_unknown_event_and_action_fail_closed(self) -> None:
        state = self.start()
        event = self.run_cli(
            "apply",
            {"type": "mystery", "expectedRevision": state["revision"]},
        )
        action = self.run_cli("authorize", {"action": "mystery"})

        self.assertEqual(event.returncode, 3)
        self.assertEqual(self.payload(event)["code"], "UNKNOWN_EVENT")
        self.assertEqual(action.returncode, 2)
        self.assertEqual(self.payload(action)["code"], "UNKNOWN_ACTION")

    def test_invalid_json_fails_closed_with_json_output(self) -> None:
        result = self.run_cli("apply", "not-json")

        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.payload(result)["code"], "INVALID_JSON")


class TestRepoTargetResolution(HarnessctlTestCase):
    """request["command"] を通じた CMD 由来の対象 repo 解決（B-4）。"""

    def setUp(self) -> None:
        super().setUp()
        self.other = self.root / "other-repo"
        self.other.mkdir()
        subprocess.run(["git", "init", "-q", str(self.other)], check=True)

    def test_command_with_cd_resolves_target_repo_for_context_validation(self) -> None:
        self.start()

        result = self.run_cli(
            "inspect",
            {"command": f"cd {self.other} && git status"},
        )

        self.assertEqual(result.returncode, 3, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "STATE_CONTEXT_MISMATCH")

    def test_command_with_unresolvable_target_denies_with_repo_target_code(self) -> None:
        self.start()

        result = self.run_cli(
            "inspect",
            {"command": "cd /no/such/directory-zzz && git status"},
        )

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        payload = self.payload(result)
        self.assertEqual(payload["code"], "REPO_TARGET_UNRESOLVABLE")
        self.assertTrue(payload["reason"])

    def test_pr_create_denies_when_gh_target_is_unresolvable(self) -> None:
        state = self.to_review()
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        attached = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )
        self.advance(self.payload(attached)["state"], "accepted")

        decision = self.run_cli(
            "authorize",
            {"action": "pr.create", "command": "gh pr create -R someone/other --fill"},
        )

        self.assertEqual(decision.returncode, 2, msg=decision.stdout + decision.stderr)
        payload = self.payload(decision)
        self.assertEqual(payload["code"], "REPO_TARGET_UNRESOLVABLE")
        self.assertTrue(payload["reason"])


class TestAssignments(HarnessctlTestCase):
    """ADR-012 §1/§2: assignment 一級状態と worker report の provenance。"""

    def assign(self, state: dict, role: str, executor: str = "codex", worker_id: str = "worker-1") -> dict:
        result = self.run_cli(
            "apply",
            {
                "type": "assignment.create",
                "expectedRevision": state["revision"],
                "role": role,
                "executor": executor,
                "workerId": worker_id,
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return self.payload(result)["state"]

    def dispatch(self, state: dict, ref: dict | None = None) -> dict:
        result = self.run_cli(
            "apply",
            {
                "type": "assignment.dispatched",
                "expectedRevision": state["revision"],
                "transport": "agmsg",
                "ref": ref or {"team": "t", "to": "worker"},
                "at": "2026-08-30T00:00:00Z",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return self.payload(result)["state"]

    def report_implement(
        self, state: dict, result_sha: str, executor: str = "codex", worker_id: str = "worker-1"
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "apply",
            {
                "type": "assignment.report",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "worker-report",
                    "trust": "audit-only",
                    "executor": executor,
                    "workerId": worker_id,
                    "resultSha": result_sha,
                    "artifact": str(self.artifact),
                    "checks": [{"command": "pytest", "exitCode": 0}],
                },
            },
        )

    def test_implement_assignment_happy_path_with_real_second_commit(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")
        assignment = state["assignments"][0]
        self.assertEqual(assignment["status"], "assigned")
        self.assertTrue(assignment["correlationId"])
        base_sha = assignment["subjectSha"]

        state = self.dispatch(state)
        self.assertEqual(state["assignments"][0]["status"], "dispatched")
        self.assertEqual(state["assignments"][0]["dispatch"]["transport"], "agmsg")

        self.commit_file("impl.txt", "worker change\n")
        new_head = self.head()
        self.assertNotEqual(base_sha, new_head)

        result = self.report_implement(state, new_head)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["assignments"][0]["status"], "reported")
        self.assertEqual(state["assignments"][0]["resultSha"], new_head)
        self.assertEqual(state["evidence"][-1]["kind"], "worker-report")
        self.assertEqual(state["evidence"][-1]["assignmentIndex"], 0)
        self.assertEqual(state["evidence"][-1]["subjectSha"], base_sha)

        advanced = self.advance(state, "implemented")
        self.assertEqual(advanced["phase"], "verify")

    def test_report_subject_stale_when_result_sha_is_not_head(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")
        state = self.dispatch(state)
        self.commit_file("impl.txt", "worker change\n")

        result = self.report_implement(state, "0" * 40)

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "REPORT_SUBJECT_STALE")

    def test_report_base_not_ancestor_when_history_was_replaced(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")
        state = self.dispatch(state)

        # base の commit を歴史から外す: 無関係な orphan branch に付け替える。
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-q", "--orphan", "detached"],
            check=True,
        )
        (self.repo / "orphan.txt").write_text("orphan\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "orphan.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "orphan"], check=True
        )
        new_head = self.head()

        result = self.report_implement(state, new_head)

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "REPORT_BASE_NOT_ANCESTOR")

    def test_assignment_active_blocks_a_second_create(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.create",
                "expectedRevision": state["revision"],
                "role": "implement",
                "executor": "codex",
                "workerId": "worker-2",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "ASSIGNMENT_ACTIVE")

    def test_assignment_role_must_match_the_current_phase(self) -> None:
        state = self.to_implement()

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.create",
                "expectedRevision": state["revision"],
                "role": "review",
                "executor": "codex",
                "workerId": "worker-1",
            },
        )

        self.assertEqual(result.returncode, 2)
        payload = self.payload(result)
        self.assertEqual(payload["code"], "ASSIGNMENT_ROLE_PHASE_MISMATCH")
        self.assertEqual(payload["role"], "review")
        self.assertEqual(payload["phase"], "implement")

    def test_invalid_assignment_phase_blocks_create_outside_implement_or_review(self) -> None:
        state = self.start()

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.create",
                "expectedRevision": state["revision"],
                "role": "implement",
                "executor": "codex",
                "workerId": "worker-1",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "INVALID_ASSIGNMENT_PHASE")

    def test_phase_advance_implemented_is_gated_on_assignment_reported(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")
        state = self.dispatch(state)

        result = self.run_cli(
            "apply",
            {
                "type": "phase.advance",
                "event": "implemented",
                "expectedRevision": state["revision"],
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "ASSIGNMENT_NOT_REPORTED")

    def test_phase_advance_implemented_without_any_assignment_is_unblocked(self) -> None:
        state = self.to_implement()

        advanced = self.advance(state, "implemented")

        self.assertEqual(advanced["phase"], "verify")

    def test_abandon_then_recreate_assignment(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.abandon",
                "expectedRevision": state["revision"],
                "reason": "worker crashed",
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["assignments"][0]["status"], "abandoned")
        self.assertEqual(state["assignments"][0]["abandonReason"], "worker crashed")

        state = self.assign(state, "implement", worker_id="worker-2")

        self.assertEqual(len(state["assignments"]), 2)
        self.assertEqual(state["assignments"][1]["status"], "assigned")
        self.assertEqual(state["assignments"][1]["workerId"], "worker-2")

    def test_abandon_requires_a_non_blank_reason(self) -> None:
        state = self.to_implement()
        state = self.assign(state, "implement")

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.abandon",
                "expectedRevision": state["revision"],
                "reason": "  ",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "ABANDON_REASON_REQUIRED")

    def test_review_assignment_reports_via_assignment_report(self) -> None:
        state = self.to_review()
        state = self.assign(state, "review", executor="claude", worker_id="reviewer-1")
        state = self.dispatch(state)
        head = self.head()

        result = self.run_cli(
            "apply",
            {
                "type": "assignment.report",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "claude",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["phase"], "decide")
        self.assertEqual(state["assignments"][0]["status"], "reported")
        self.assertEqual(state["evidence"][-1]["assignmentIndex"], 0)

    def test_review_assignment_reports_via_legacy_review_attach(self) -> None:
        state = self.to_review()
        state = self.assign(state, "review", executor="claude", worker_id="reviewer-1")
        state = self.dispatch(state)
        head = self.head()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "claude",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["phase"], "decide")
        self.assertEqual(state["assignments"][0]["status"], "reported")
        self.assertEqual(state["evidence"][-1]["assignmentIndex"], 0)

    def test_review_attach_aliases_a_review_assignment_that_was_never_dispatched(self) -> None:
        """coordinator が dispatched を忘れても attach で reported まで進み、
        次の assignment.create を ASSIGNMENT_ACTIVE で詰まらせない。"""
        state = self.to_review()
        state = self.assign(state, "review", executor="claude", worker_id="reviewer-1")
        head = self.head()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "claude",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["assignments"][0]["status"], "reported")
        self.assertEqual(state["evidence"][-1]["assignmentIndex"], 0)

    def test_review_attach_without_a_current_assignment_stays_legacy(self) -> None:
        """assignment を一切使わない従来の review.attach は assignments に触れない。"""
        state = self.to_review()
        head = self.head()

        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": head,
                    "artifact": str(self.artifact),
                },
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["assignments"], [])
        self.assertNotIn("assignmentIndex", state["evidence"][-1])


class TestSchemaVersionCompatibility(HarnessctlTestCase):
    """ADR-012 §6: schemaVersion 1 の state は非アクティブなら読めて上書きできる。

    active な v1 state は旧 kernel で完了させる前提で止める。
    """

    def write_v1_state(self, *, phase: str, revision: int, task_id: str = "OLD-1") -> None:
        git_dir = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--absolute-git-dir"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        worktree_root = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        state = {
            "schemaVersion": 1,
            "revision": revision,
            "phase": phase,
            "task": {"id": task_id},
            "workflow": {"name": "change", "version": "0" * 64},
            "context": {"gitDir": git_dir, "worktreeRoot": worktree_root},
            "evidence": [],
            "reviewAttempts": 0,
        }
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

    def test_complete_v1_state_is_replaced_by_task_start(self) -> None:
        self.write_v1_state(phase="complete", revision=5)

        result = self.run_cli("apply", {"type": "task.start", "taskId": "NEW-1"})

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.payload(result)["state"]
        self.assertEqual(state["schemaVersion"], 2)
        self.assertEqual(state["task"]["id"], "NEW-1")
        self.assertEqual(state["assignments"], [])

    def test_untouched_intake_v1_state_is_replaced_by_task_start(self) -> None:
        self.write_v1_state(phase="intake", revision=0)

        result = self.run_cli("apply", {"type": "task.start", "taskId": "NEW-1"})

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["state"]["task"]["id"], "NEW-1")

    def test_active_v1_state_is_unsupported_on_inspect(self) -> None:
        self.write_v1_state(phase="isolate", revision=1)

        result = self.run_cli("inspect", {})

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "STATE_SCHEMA_VERSION_UNSUPPORTED")

    def test_active_v1_state_blocks_task_start(self) -> None:
        self.write_v1_state(phase="isolate", revision=1)

        result = self.run_cli("apply", {"type": "task.start", "taskId": "NEW-1"})

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "STATE_SCHEMA_VERSION_UNSUPPORTED")

    def test_inactive_v1_state_on_non_start_apply_is_unsupported_not_internal_error(self) -> None:
        """intake・revision 0 の v1 state は非アクティブだが、task.start 以外の
        apply は v2 の assignments 前提なので KeyError(INTERNAL_CONTRACT_VIOLATION)
        ではなく STATE_SCHEMA_VERSION_UNSUPPORTED で止まるべき。"""
        self.write_v1_state(phase="intake", revision=0)

        result = self.run_cli(
            "apply",
            {"type": "phase.advance", "event": "requirements_clear", "expectedRevision": 0},
        )

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "STATE_SCHEMA_VERSION_UNSUPPORTED")

    def test_active_v1_state_blocks_authorize(self) -> None:
        self.write_v1_state(phase="publish", revision=3)

        result = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertEqual(self.payload(result)["code"], "STATE_SCHEMA_VERSION_UNSUPPORTED")


class TestReviewRemediationAndQuotaSkip(HarnessctlTestCase):
    """rules/codex-review-policy.md の「指摘は全件修正・再レビューなし」「quota 切れは SKIP」を
    kernel が通せることを検証する。"""

    def attach(self, state: dict) -> dict:
        result = self.run_cli(
            "apply",
            {
                "type": "review.attach",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "local-review",
                    "trust": "audit-only",
                    "provider": "codex",
                    "subjectSha": self.head(),
                    "artifact": str(self.artifact),
                },
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return self.payload(result)["state"]

    def skip(self, state: dict, reason: str = "usage limit reached") -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "apply",
            {
                "type": "review.skip",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "review-skipped",
                    "trust": "audit-only",
                    "provider": "codex",
                    "skipReason": "quota",
                    "reason": reason,
                },
            },
        )

    def test_pr_create_is_allowed_after_remediation_commits_without_a_second_review(self) -> None:
        state = self.to_review()
        reviewed = self.head()
        state = self.attach(state)
        state = self.advance(state, "findings_fixed")
        self.assertEqual(state["phase"], "publish")
        self.commit_file("fix.txt", "remediation\n")
        self.assertNotEqual(self.head(), reviewed)

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 0, msg=decision.stdout + decision.stderr)
        self.assertEqual(self.payload(decision)["code"], "LOCAL_REVIEW_ANCESTOR")
        self.assertEqual(self.payload(decision)["trust"], "audit-only")

    def test_pr_create_stays_denied_when_reviewed_commit_is_not_an_ancestor(self) -> None:
        state = self.to_review()
        state = self.attach(state)
        self.advance(state, "accepted")
        # ブランチを作り直したのと同じ状況: レビューした commit が履歴から消える
        subprocess.run(
            ["git", "-C", str(self.repo), "reset", "-q", "--hard", "HEAD~0"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten"],
            check=True,
        )

        decision = self.run_cli("authorize", {"action": "pr.create"})

        self.assertEqual(decision.returncode, 2)
        self.assertEqual(self.payload(decision)["code"], "REVIEW_STALE")

    def test_review_skip_records_quota_evidence_and_moves_to_publish(self) -> None:
        state = self.to_review()

        result = self.skip(state)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        updated = self.payload(result)["state"]
        self.assertEqual(updated["phase"], "publish")
        evidence = updated["evidence"][-1]
        self.assertEqual(evidence["kind"], "review-skipped")
        self.assertEqual(evidence["skipReason"], "quota")
        self.assertEqual(evidence["subjectSha"], self.head())
        self.assertEqual(updated["reviewAttempts"], 0)

        decision = self.run_cli("authorize", {"action": "pr.create"})
        self.assertEqual(decision.returncode, 0, msg=decision.stdout + decision.stderr)
        self.assertEqual(self.payload(decision)["code"], "LOCAL_REVIEW_SKIPPED")

    def test_review_skip_outside_review_phase_is_rejected(self) -> None:
        state = self.to_implement()

        result = self.skip(state)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "INVALID_REVIEW_PHASE")

    def test_review_skip_requires_a_reason_and_quota_skip_reason(self) -> None:
        state = self.to_review()

        blank = self.skip(state, reason="   ")
        self.assertEqual(self.payload(blank)["code"], "REVIEW_SKIP_REASON_REQUIRED")

        other = self.run_cli(
            "apply",
            {
                "type": "review.skip",
                "expectedRevision": state["revision"],
                "evidence": {
                    "kind": "review-skipped",
                    "trust": "audit-only",
                    "skipReason": "connection",
                    "reason": "network down",
                },
            },
        )
        self.assertEqual(self.payload(other)["code"], "INVALID_REVIEW_EVIDENCE")

    def test_review_skipped_transition_cannot_be_advanced_by_hand(self) -> None:
        state = self.to_review()

        result = self.run_cli(
            "apply",
            {"type": "phase.advance", "event": "review_skipped", "expectedRevision": state["revision"]},
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.payload(result)["code"], "PROTECTED_TRANSITION")


if __name__ == "__main__":
    unittest.main()

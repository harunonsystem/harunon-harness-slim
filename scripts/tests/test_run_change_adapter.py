#!/usr/bin/env python3
"""Portable run-change adapter smoke test."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER = REPO_ROOT / "packages/core/skills/run-change/scripts/harness.py"
SKILL = REPO_ROOT / "packages/core/skills/run-change/SKILL.md"


class TestRunChangeAdapter(unittest.TestCase):
    def run_adapter(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ADAPTER), "--repo", str(repo), *args],
            capture_output=True,
            text=True,
        )

    def test_start_and_status_use_the_json_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            started = subprocess.run(
                [sys.executable, str(ADAPTER), "--repo", str(repo), "start", "HAR-1"],
                capture_output=True,
                text=True,
            )
            status = subprocess.run(
                [sys.executable, str(ADAPTER), "--repo", str(repo), "status"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(started.returncode, 0, msg=started.stdout + started.stderr)
            self.assertEqual(status.returncode, 0, msg=status.stdout + status.stderr)
            self.assertEqual(json.loads(status.stdout)["state"]["task"]["id"], "HAR-1")

    def test_attach_review_rejects_missing_artifact_before_kernel_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            result = self.run_adapter(
                repo,
                "attach-review",
                "--revision",
                "0",
                "--provider",
                "codex",
                "--subject-sha",
                "0" * 40,
                "--artifact",
                str(repo / "missing.txt"),
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["code"], "REVIEW_ARTIFACT_NOT_FOUND")

    def test_publish_only_start_enters_review_without_change_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            started = self.run_adapter(repo, "start", "HAR-PR", "--publish-only")

            self.assertEqual(started.returncode, 0, msg=started.stdout + started.stderr)
            state = json.loads(started.stdout)["state"]
            self.assertEqual(state["phase"], "review")
            self.assertEqual(state["revision"], 0)

    def test_assign_dispatched_report_and_abandon_translate_to_kernel_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                check=True,
            )
            (repo / "README.md").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)

            started = self.run_adapter(repo, "start", "HAR-ASSIGN")
            state = json.loads(started.stdout)["state"]
            for event in ("requirements_clear", "isolated", "planned"):
                advanced = self.run_adapter(repo, "advance", event, "--revision", str(state["revision"]))
                self.assertEqual(advanced.returncode, 0, msg=advanced.stdout + advanced.stderr)
                state = json.loads(advanced.stdout)["state"]

            assigned = self.run_adapter(
                repo,
                "assign",
                "implement",
                "--executor",
                "codex",
                "--worker-id",
                "worker-1",
                "--revision",
                str(state["revision"]),
            )
            self.assertEqual(assigned.returncode, 0, msg=assigned.stdout + assigned.stderr)
            state = json.loads(assigned.stdout)["state"]
            self.assertEqual(state["assignments"][0]["status"], "assigned")
            self.assertTrue(state["assignments"][0]["correlationId"])

            dispatched = self.run_adapter(
                repo,
                "dispatched",
                "--transport",
                "agmsg",
                "--ref",
                json.dumps({"team": "t", "to": "worker-1"}),
                "--at",
                "2026-08-30T00:00:00Z",
                "--revision",
                str(state["revision"]),
            )
            self.assertEqual(dispatched.returncode, 0, msg=dispatched.stdout + dispatched.stderr)
            state = json.loads(dispatched.stdout)["state"]
            self.assertEqual(state["assignments"][0]["status"], "dispatched")

            (repo / "impl.txt").write_text("worker change\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "impl.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "impl"], check=True)
            new_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            report_artifact = Path(tmp) / "report.txt"
            report_artifact.write_text("worker done\n", encoding="utf-8")

            reported = self.run_adapter(
                repo,
                "report",
                "--revision",
                str(state["revision"]),
                "--executor",
                "codex",
                "--worker-id",
                "worker-1",
                "--result-sha",
                new_head,
                "--artifact",
                str(report_artifact),
                "--checks",
                json.dumps([{"command": "pytest", "exitCode": 0}]),
            )
            self.assertEqual(reported.returncode, 0, msg=reported.stdout + reported.stderr)
            state = json.loads(reported.stdout)["state"]
            self.assertEqual(state["assignments"][0]["status"], "reported")
            self.assertEqual(state["evidence"][-1]["kind"], "worker-report")

            second_assign = self.run_adapter(
                repo,
                "assign",
                "implement",
                "--executor",
                "codex",
                "--worker-id",
                "worker-2",
                "--revision",
                str(state["revision"]),
            )
            self.assertEqual(second_assign.returncode, 0, msg=second_assign.stdout + second_assign.stderr)
            state = json.loads(second_assign.stdout)["state"]

            abandoned = self.run_adapter(
                repo,
                "abandon",
                "--reason",
                "worker unresponsive",
                "--revision",
                str(state["revision"]),
            )
            self.assertEqual(abandoned.returncode, 0, msg=abandoned.stdout + abandoned.stderr)
            state = json.loads(abandoned.stdout)["state"]
            self.assertEqual(state["assignments"][1]["status"], "abandoned")
            self.assertEqual(state["assignments"][1]["abandonReason"], "worker unresponsive")

    def test_report_rejects_missing_artifact_before_kernel_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            result = self.run_adapter(
                repo,
                "report",
                "--revision",
                "0",
                "--executor",
                "codex",
                "--worker-id",
                "worker-1",
                "--result-sha",
                "0" * 40,
                "--artifact",
                str(repo / "missing.txt"),
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["code"], "REVIEW_ARTIFACT_NOT_FOUND")

    def test_codex_review_stays_inside_the_active_codex_runtime(self) -> None:
        instructions = SKILL.read_text(encoding="utf-8")

        self.assertIn("review_model", instructions)
        self.assertIn("reviewer", instructions)
        self.assertIn("GitHub app", instructions)
        self.assertNotIn("codex_review.py", instructions)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""rigor-profile.sh の rigor_profile() 判定テスト（ADR-009）。

lib 単体を bash -c で source して直接呼び出す（hook を経由しない）。
判定順: patterns ファイル first-match-wins > local ファイルの defaultProfile
> "rigorous"（fail-safe）。

末尾に配線テスト: rigorous 専用 gate hook（block-pr-without-codex-review.sh）が
casual profile では早期 exit で素通しすることを確認する。
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RIGOR_LIB = REPO_ROOT / "packages" / "core" / "hooks" / "lib" / "rigor-profile.sh"
PR_GATE_HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-pr-without-codex-review.sh"


class RigorProfileTestCase(unittest.TestCase):
    """一時ディレクトリに patterns/local ファイルを隔離するための基底クラス。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 既定では両ファイルとも存在しない未設定状態にする
        self.patterns_file = self.root / "rigor-patterns.json"
        self.local_file = self.root / "rigor.local.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _rigor_profile(self, repo_root: str = "", cwd: str = None) -> str:
        env = dict(os.environ)
        env["RIGOR_PATTERNS_FILE"] = str(self.patterns_file)
        env["RIGOR_LOCAL_FILE"] = str(self.local_file)
        script = f'source "{RIGOR_LIB}"; rigor_profile "$1"'
        result = subprocess.run(
            ["bash", "-c", script, "_", repo_root],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stdout.strip(), result.stderr

    def _write_patterns(self, patterns: list) -> None:
        self.patterns_file.write_text(json.dumps(patterns), encoding="utf-8")

    def _write_local(self, config: dict) -> None:
        self.local_file.write_text(json.dumps(config), encoding="utf-8")


class TestRigorProfileDefaults(RigorProfileTestCase):
    def test_no_files_defaults_to_rigorous(self):
        stdout, _ = self._rigor_profile(repo_root="/some/repo")
        self.assertEqual(stdout, "rigorous")

    def test_patterns_match_returns_casual(self):
        self._write_patterns([{"pattern": "*/harunon-harness", "profile": "casual"}])
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "casual")

    def test_patterns_match_github_remote_owner_and_repo(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:example-org/example-dashboard.git"],
            check=True,
            capture_output=True,
        )
        self._write_patterns([{"pattern": "example-org/example-*", "profile": "rigorous"}])
        stdout, _ = self._rigor_profile(repo_root=str(repo))
        self.assertEqual(stdout, "rigorous")

    def test_patterns_no_match_falls_back_to_default(self):
        self._write_patterns([{"pattern": "*/other-repo", "profile": "casual"}])
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")

    def test_first_match_wins(self):
        self._write_patterns(
            [
                {"pattern": "*/harunon-harness", "profile": "rigorous"},
                {"pattern": "*/harunon-harness", "profile": "casual"},
            ]
        )
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")

    def test_local_default_profile_used_when_no_pattern_match(self):
        self._write_local({"defaultProfile": "casual"})
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "casual")

    def test_pattern_match_takes_precedence_over_local_default(self):
        self._write_patterns([{"pattern": "*/harunon-harness", "profile": "rigorous"}])
        self._write_local({"defaultProfile": "casual"})
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")

    def test_broken_patterns_json_falls_back_and_warns(self):
        self.patterns_file.write_text("{not valid json", encoding="utf-8")
        stdout, stderr = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")
        self.assertIn("壊れた JSON", stderr)

    def test_broken_local_json_falls_back_and_warns(self):
        self.local_file.write_text("{not valid json", encoding="utf-8")
        stdout, stderr = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")
        self.assertIn("壊れた JSON", stderr)

    def test_unknown_profile_value_in_patterns_falls_back(self):
        self._write_patterns([{"pattern": "*/harunon-harness", "profile": "yolo"}])
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")

    def test_unknown_default_profile_in_local_falls_back(self):
        self._write_local({"defaultProfile": "yolo"})
        stdout, _ = self._rigor_profile(repo_root="/Users/x/harunon-harness")
        self.assertEqual(stdout, "rigorous")

    def test_git_external_repo_root_skips_patterns_uses_local(self):
        """repo_root 省略時に git 外の cwd で呼ぶと patterns 判定はスキップされ local に落ちる。"""
        self._write_patterns([{"pattern": "*", "profile": "casual"}])
        self._write_local({"defaultProfile": "casual"})
        stdout, _ = self._rigor_profile(repo_root="", cwd="/")
        self.assertEqual(stdout, "casual")

    def test_git_external_repo_root_with_no_local_defaults_to_rigorous(self):
        self._write_patterns([{"pattern": "*", "profile": "casual"}])
        stdout, _ = self._rigor_profile(repo_root="", cwd="/")
        self.assertEqual(stdout, "rigorous")


class TestRigorProfileHookWiring(unittest.TestCase):
    """rigorous 専用 gate hook が casual profile で早期 exit すること（配線確認）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", str(self.repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
        )
        self.patterns_file = self.root / "rigor-patterns.json"
        self.local_file = self.root / "rigor.local.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_casual_profile_skips_pr_gate_before_denial(self):
        git_root = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.patterns_file.write_text(
            json.dumps([{"pattern": git_root, "profile": "casual"}]), encoding="utf-8"
        )

        env = dict(os.environ)
        env["RIGOR_PATTERNS_FILE"] = str(self.patterns_file)
        env["RIGOR_LOCAL_FILE"] = str(self.local_file)
        json_input = json.dumps({"tool_input": {"command": "gh pr create --title 'test'"}})
        result = subprocess.run(
            ["bash", str(PR_GATE_HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "",
            msg="casual profile では gate flag が無くても deny せず素通しする",
        )
        self.assertNotIn("deny", result.stdout)

    def test_rigorous_profile_still_denies_without_flag(self):
        """env 未設定（patterns/local 不在）では従来どおり rigorous で deny を維持する。"""
        env = dict(os.environ)
        env["RIGOR_PATTERNS_FILE"] = str(self.patterns_file)
        env["RIGOR_LOCAL_FILE"] = str(self.local_file)
        json_input = json.dumps({"tool_input": {"command": "gh pr create --title 'test'"}})
        result = subprocess.run(
            ["bash", str(PR_GATE_HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)


if __name__ == "__main__":
    unittest.main()

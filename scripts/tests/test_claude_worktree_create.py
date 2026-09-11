#!/usr/bin/env python3
"""Claude の WorktreeCreate hook が gwm に委譲する契約のテスト。"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "claude-worktree-create.sh"


class TestClaudeWorktreeCreate(unittest.TestCase):
    def _run(self, name: Optional[str] = "feature/foo", fake_gwm_output: Optional[str] = None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            worktree = tmp_path / "worktree"
            worktree.mkdir()
            log = tmp_path / "gwm.log"
            fake_gwm = tmp_path / "gwm"
            fake_gwm.write_text(
                "#!/bin/bash\n"
                "printf '%s|%s|%s\\n' \"$PWD\" \"$1\" \"$2\" > \"$GWM_TEST_LOG\"\n"
                "printf '%s\\n' \"$GWM_TEST_OUTPUT\"\n"
            )
            fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["PATH"] = "{}:{}".format(tmp, env.get("PATH", ""))
            env["GWM_TEST_LOG"] = str(log)
            env["GWM_TEST_OUTPUT"] = fake_gwm_output or str(worktree)
            payload = {"cwd": str(repo)}
            if name is not None:
                payload["name"] = name
            result = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps({"hook_event_name": "WorktreeCreate", **payload}),
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(REPO_ROOT),
                env=env,
            )
            return result, log.read_text() if log.exists() else ""

    def test_delegates_name_and_cwd_to_gwm_and_returns_last_output_path(self):
        result, log = self._run(
            fake_gwm_output="status from gwm\n" + tempfile.gettempdir()
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), tempfile.gettempdir())
        self.assertTrue(log.endswith("|add|feature/foo\n"))

    def test_rejects_missing_worktree_name(self):
        result, _ = self._run(name=None)
        self.assertNotEqual(result.returncode, 0)

    def test_climbs_to_superproject_when_cwd_is_inside_a_submodule(self):
        """cwd が submodule 内でも worktree は最外殻のリポジトリに作る。

        調査で cd した packages/extras/_active が session cwd に残ったまま
        EnterWorktree(name:) を呼ぶと、extras 側の worktree が作られる実害が
        出た（2026-07-26）。gwm が受け取る $PWD が親リポジトリ側になることを固定する。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            def init_repo(path: Path) -> None:
                subprocess.run(["git", "init", "-q", str(path)], check=True)
                subprocess.run(
                    ["git", "-C", str(path), "config", "user.email", "test@example.com"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(path), "config", "user.name", "Test"], check=True
                )
                (path / "README.md").write_text("fixture\n")
                subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
                subprocess.run(
                    ["git", "-C", str(path), "commit", "-qm", "initial"], check=True
                )

            sub_origin = tmp_path / "sub-origin"
            sub_origin.mkdir()
            init_repo(sub_origin)
            parent = tmp_path / "parent"
            parent.mkdir()
            init_repo(parent)
            # 新しめの git は file:// submodule を既定で拒否するため明示的に許可する
            subprocess.run(
                [
                    "git", "-C", str(parent),
                    "-c", "protocol.file.allow=always",
                    "submodule", "add", "-q", str(sub_origin), "sub",
                ],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(parent), "commit", "-qm", "add submodule"], check=True
            )

            log = tmp_path / "gwm.log"
            fake_gwm = tmp_path / "gwm"
            fake_gwm.write_text(
                "#!/bin/bash\n"
                "printf '%s|%s|%s\\n' \"$PWD\" \"$1\" \"$2\" > \"$GWM_TEST_LOG\"\n"
                "printf '%s\\n' \"$GWM_TEST_OUTPUT\"\n"
            )
            fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["PATH"] = "{}:{}".format(tmp, env.get("PATH", ""))
            env["GWM_TEST_LOG"] = str(log)
            env["GWM_TEST_OUTPUT"] = str(tmp_path)

            result = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "WorktreeCreate",
                        "cwd": str(parent / "sub"),
                        "name": "feature/foo",
                    }
                ),
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO_ROOT), env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            gwm_pwd = log.read_text().split("|", 1)[0]
            self.assertEqual(Path(gwm_pwd).resolve(), parent.resolve())
            self.assertIn("superproject に寄せます", result.stderr)

    def test_bases_on_fetched_origin_default_branch_when_origin_exists(self):
        """origin がある repo では、ローカル main ではなく fetch 済みの origin/<default> を base に渡す。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            remote = tmp_path / "remote"
            local = tmp_path / "local"
            git_env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="t@example.com",
                           GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="t@example.com")

            def git(*args, cwd):
                subprocess.run(["git", *args], cwd=str(cwd), check=True, env=git_env,
                               capture_output=True, text=True)

            git("init", "-q", "-b", "main", str(remote), cwd=tmp_path)
            git("commit", "-q", "--allow-empty", "-m", "base", cwd=remote)
            git("clone", "-q", str(remote), str(local), cwd=tmp_path)
            # remote だけが進み、local は fetch していない状態を作る
            git("commit", "-q", "--allow-empty", "-m", "remote-only", cwd=remote)
            remote_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(remote), check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            log = tmp_path / "gwm.log"
            fake_gwm = tmp_path / "gwm"
            fake_gwm.write_text(
                "#!/bin/bash\n"
                "printf '%s\\n' \"$*\" > \"$GWM_TEST_LOG\"\n"
                "git -C \"$PWD\" rev-parse origin/main >> \"$GWM_TEST_LOG\"\n"
                "printf '%s\\n' \"$GWM_TEST_OUTPUT\"\n"
            )
            fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["PATH"] = "{}:{}".format(tmp, env.get("PATH", ""))
            env["GWM_TEST_LOG"] = str(log)
            env["GWM_TEST_OUTPUT"] = str(tmp_path)

            result = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps(
                    {"hook_event_name": "WorktreeCreate", "cwd": str(local), "name": "feature/foo"}
                ),
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(REPO_ROOT),
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args_line, fetched_ref = log.read_text().splitlines()
            self.assertEqual(args_line, "add --from origin/main feature/foo")
            # hook が fetch したので、gwm 実行時点で origin/main は remote の最新を指す
            self.assertEqual(fetched_ref, remote_head)

    def test_creates_a_real_git_worktree_through_the_gwm_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            worktree_root = tmp_path / "worktrees"
            worktree_root.mkdir()
            branch = "feature-e2e"

            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Test"],
                check=True,
            )
            (repo / "README.md").write_text("fixture\n")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"], check=True
            )

            fake_gwm = tmp_path / "gwm"
            fake_gwm.write_text(
                "#!/bin/bash\n"
                "set -eu\n"
                "branch=\"$2\"\n"
                "path=\"$GWM_TEST_ROOT/$branch\"\n"
                "git -C \"$PWD\" worktree add -q -b \"$branch\" \"$path\" HEAD\n"
                "printf '%s\\n' \"$path\"\n"
            )
            fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["PATH"] = "{}:{}".format(tmp, env.get("PATH", ""))
            env["GWM_TEST_ROOT"] = str(worktree_root)

            result = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "WorktreeCreate",
                        "cwd": str(repo),
                        "name": branch,
                    }
                ),
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(REPO_ROOT),
                env=env,
            )
            worktree_path = Path(result.stdout.strip())
            try:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(worktree_path, worktree_root / branch)
                self.assertTrue(worktree_path.is_dir())
                worktree_list = subprocess.run(
                    ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                self.assertIn(f"worktree {worktree_path.resolve()}\n", worktree_list)
                self.assertIn(f"branch refs/heads/{branch}\n", worktree_list)
            finally:
                if worktree_path.is_dir() and worktree_path != repo:
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(repo),
                            "worktree",
                            "remove",
                            "--force",
                            str(worktree_path),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )


if __name__ == "__main__":
    unittest.main()

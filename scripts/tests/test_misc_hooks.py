#!/usr/bin/env python3
"""check-plan-model.sh / log-compaction.sh / verify-before-commit.sh / verify-before-push.sh
のスモークテスト。

各 hook を subprocess として実行し、正常系の exit code / 主要分岐 1-2 個を検証する。
外部コマンド（claude CLI, 実 HOME）には依存しない: check-plan-model は PATH 上に
fake `claude` バイナリを差し込んで決定的に分岐させる。

テスト作成中に発見したバグ（本プランでは修正しない）は @unittest.expectedFailure
でマークし、クラスの docstring / NOTES で報告する:
- verify-before-commit.sh / verify-before-push.sh は、トリガー語（commit/push）を含む
  不正な JSON を渡すと jq のパースエラーで exit 5 crash する（"壊れた JSON でクラッシュ
  しない" という Done criteria に反する）
- log-compaction.sh は $HOME/.claude/ が存在しない環境で exit 1 crash する
  （親ディレクトリを mkdir しない）。実運用では ~/.claude/ は常に存在するため実害は
  低いが、フィクスチャ上は容易に再現する
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "packages" / "core" / "hooks"
CHECK_PLAN_MODEL_HOOK = HOOKS_DIR / "check-plan-model.sh"
LOG_COMPACTION_HOOK = HOOKS_DIR / "log-compaction.sh"
VERIFY_BEFORE_COMMIT_HOOK = HOOKS_DIR / "verify-before-commit.sh"
BLOCK_SECRETS_IN_COMMIT_HOOK = HOOKS_DIR / "block-secrets-in-commit.sh"
VERIFY_BEFORE_PUSH_HOOK = HOOKS_DIR / "verify-before-push.sh"
LOG_PERMISSION_DENIED_HOOK = HOOKS_DIR / "log-permission-denied.sh"


def _run(
    hook: Path, input_text: str = "", env: dict = None, cwd: str = None
) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        for key, value in env.items():
            if value is None:
                full_env.pop(key, None)
            else:
                full_env[key] = value
    return subprocess.run(
        ["bash", str(hook)],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
        env=full_env,
    )


def _make_git_repo(parent: Path, branch: str = "feature-x") -> Path:
    repo = parent / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


class TestCheckPlanModel(unittest.TestCase):
    """SessionStart フック。HARNESS_EXPECTED_PLAN/ORG が未設定なら即 OK。

    設定時は claude auth status --json を呼ぶため、fake claude バイナリを PATH の
    先頭に差し込んで実ログイン状態に依存しない決定的なテストにする。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_bin = Path(self._tmp.name) / "bin"
        self.fake_bin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_fake_claude(self, script: str) -> None:
        claude = self.fake_bin / "claude"
        claude.write_text(script)
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)

    def _run_with_fake_path(self, env: dict) -> subprocess.CompletedProcess:
        full_env = dict(env)
        full_env["PATH"] = "{}:{}".format(self.fake_bin, os.environ.get("PATH", ""))
        return _run(CHECK_PLAN_MODEL_HOOK, env=full_env)

    def test_no_expected_env_vars_prints_ok(self):
        result = _run(
            CHECK_PLAN_MODEL_HOOK,
            env={"HARNESS_EXPECTED_PLAN": None, "HARNESS_EXPECTED_ORG": None},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "OK")

    def test_auth_status_unavailable_warns_and_allows(self):
        self._write_fake_claude("#!/bin/bash\nexit 1\n")
        result = self._run_with_fake_path(
            {"HARNESS_EXPECTED_PLAN": "max", "HARNESS_EXPECTED_ORG": "acme"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("取得に失敗", result.stdout)

    def test_matching_plan_and_org_prints_ok(self):
        self._write_fake_claude(
            "#!/bin/bash\n"
            'echo \'{"subscriptionType":"max","orgName":"acme","email":"me@example.com"}\'\n'
        )
        result = self._run_with_fake_path(
            {"HARNESS_EXPECTED_PLAN": "max", "HARNESS_EXPECTED_ORG": "acme"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "OK")

    def test_not_logged_in_prompts_login_instead_of_mismatch(self):
        # login 前の SessionStart で「アカウント不一致」と誤発報していた
        # （2026-08-09）。未ログインはログイン案内だけ出して素通しする。
        self._write_fake_claude(
            "#!/bin/bash\n" 'echo \'{"loggedIn":false}\'\n'
        )
        result = self._run_with_fake_path(
            {"HARNESS_EXPECTED_PLAN": "max", "HARNESS_EXPECTED_ORG": "acme"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("未ログイン", result.stdout)
        self.assertNotIn("アカウント不一致", result.stdout)

    def test_mismatched_plan_and_org_warns_and_allows(self):
        self._write_fake_claude(
            "#!/bin/bash\n"
            'echo \'{"subscriptionType":"max","orgName":"acme","email":"me@example.com"}\'\n'
        )
        result = self._run_with_fake_path(
            {"HARNESS_EXPECTED_PLAN": "pro", "HARNESS_EXPECTED_ORG": "other"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("🚨", result.stdout)
        self.assertIn("アカウント不一致", result.stdout)


class TestLogCompaction(unittest.TestCase):
    """PreCompact フック。~/.claude/compaction.log に追記し、直近100行のみ保持する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fake_home = self.root / "home"
        (self.fake_home / ".claude").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_logs_branch_and_project_inside_git_repo(self):
        repo = _make_git_repo(self.root, branch="feature-x")
        result = _run(
            LOG_COMPACTION_HOOK, env={"HOME": str(self.fake_home)}, cwd=str(repo)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = self.fake_home / ".claude" / "compaction.log"
        self.assertTrue(log.exists())
        content = log.read_text()
        self.assertIn("project=repo", content)
        self.assertIn("branch=feature-x", content)

    def test_outside_git_repo_logs_dash_branch(self):
        outside = self.root / "not-a-repo"
        outside.mkdir()
        result = _run(
            LOG_COMPACTION_HOOK, env={"HOME": str(self.fake_home)}, cwd=str(outside)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        content = (self.fake_home / ".claude" / "compaction.log").read_text()
        self.assertIn("branch=-", content)

    def test_log_is_truncated_to_last_100_lines(self):
        repo = _make_git_repo(self.root, branch="feature-x")
        log = self.fake_home / ".claude" / "compaction.log"
        log.write_text("\n".join(f"dummy-line-{i}" for i in range(150)) + "\n")

        result = _run(
            LOG_COMPACTION_HOOK, env={"HOME": str(self.fake_home)}, cwd=str(repo)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = log.read_text().splitlines()
        self.assertLessEqual(len(lines), 100)
        self.assertIn("project=repo", lines[-1])

    def test_missing_claude_dir_does_not_crash(self):
        """$HOME/.claude/ が存在しなくても mkdir -p でクラッシュしない。"""
        repo = _make_git_repo(self.root, branch="feature-x")
        home_without_claude_dir = self.root / "home-bare"
        home_without_claude_dir.mkdir()
        result = _run(
            LOG_COMPACTION_HOOK,
            env={"HOME": str(home_without_claude_dir)},
            cwd=str(repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


class TestLogPermissionDenied(unittest.TestCase):
    """PermissionDenied フック。~/.claude/permission-denied.log に JSONL で追記し、
    直近500行のみ保持する。ブロックも classifier retry もしない（常に exit 0、stdout 無し）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fake_home = self.root / "home"
        (self.fake_home / ".claude").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_hook(self, payload: dict) -> subprocess.CompletedProcess:
        return _run(
            LOG_PERMISSION_DENIED_HOOK,
            input_text=json.dumps(payload),
            env={"HOME": str(self.fake_home)},
        )

    def _read_log_lines(self):
        log = self.fake_home / ".claude" / "permission-denied.log"
        return [json.loads(line) for line in log.read_text().splitlines()]

    def test_classifier_denial_for_bash_logs_command(self):
        payload = {
            "session_id": "s1",
            "hook_event_name": "PermissionDenied",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
            "reason": "looked destructive",
            "source": "classifier",
            "classifier_version": "v1",
            "permission_mode": "default",
        }
        result = self._run_hook(payload)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout, "")

        lines = self._read_log_lines()
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual(entry["command"], "rm -rf /")
        self.assertEqual(entry["source"], "classifier")
        self.assertEqual(entry["tool_name"], "Bash")
        self.assertEqual(entry["session_id"], "s1")
        self.assertEqual(entry["reason"], "looked destructive")
        self.assertEqual(entry["permission_mode"], "default")
        self.assertEqual(entry["tool_input"], {"command": "rm -rf /"})

    def test_rule_denial_for_edit_logs_file_path_as_command(self):
        payload = {
            "session_id": "s2",
            "hook_event_name": "PermissionDenied",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/etc/passwd", "old_string": "x", "new_string": "y"},
            "reason": "denied by rule",
            "source": "rule",
            "permission_mode": "default",
        }
        result = self._run_hook(payload)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        lines = self._read_log_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["command"], "/etc/passwd")
        self.assertEqual(lines[0]["source"], "rule")

    def test_home_without_claude_dir_creates_it_and_does_not_crash(self):
        home_without_claude_dir = self.root / "home-bare"
        home_without_claude_dir.mkdir()
        payload = {
            "session_id": "s3",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "reason": "test",
            "source": "classifier",
            "permission_mode": "default",
        }
        result = _run(
            LOG_PERMISSION_DENIED_HOOK,
            input_text=json.dumps(payload),
            env={"HOME": str(home_without_claude_dir)},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = home_without_claude_dir / ".claude" / "permission-denied.log"
        self.assertTrue(log.exists())

    def test_log_is_truncated_to_last_500_lines(self):
        log = self.fake_home / ".claude" / "permission-denied.log"
        log.write_text(
            "\n".join(
                json.dumps({"command": f"dummy-{i}"}) for i in range(505)
            )
            + "\n"
        )

        payload = {
            "session_id": "s4",
            "tool_name": "Bash",
            "tool_input": {"command": "new-entry"},
            "reason": "test",
            "source": "classifier",
            "permission_mode": "default",
        }
        result = self._run_hook(payload)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        lines = self._read_log_lines()
        self.assertEqual(len(lines), 500)
        self.assertEqual(lines[-1]["command"], "new-entry")


class TestVerifyBeforeCommit(unittest.TestCase):
    """PreToolUse:Bash。commit コマンドに additionalContext のリマインドを付与する
    （実際に exit 2 でブロックする挙動は無い。advisory-only hook）。
    """

    def test_git_commit_command_gets_reminder(self):
        json_input = json.dumps({"tool_input": {"command": "git commit -m 'x'"}})
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("COMMIT前チェック", result.stdout)

    def test_unrelated_command_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_input_without_trigger_word_is_noop(self):
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text="totally unrelated garbage")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_input_with_trigger_word_does_not_crash(self):
        """'commit' を含む不正な JSON でも fail-open で exit 0（jq パースエラーで crash しない）。"""
        result = _run(
            VERIFY_BEFORE_COMMIT_HOOK, input_text="not valid json but has commit word"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_commit_after_every_command_boundary_gets_reminder(self):
        """改行 / & / bare subshell / $( ) の直後の commit も検出する（旧 regex は素通り）。"""
        for command in (
            "echo x\ngit commit -m 'x'",
            "sleep 1 & git commit -m 'x'",
            "(git commit -m 'x')",
            "echo $(git commit -m 'x')",
            "true;git -C . commit -m 'x'",
        ):
            with self.subTest(command=command):
                json_input = json.dumps({"tool_input": {"command": command}})
                result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input)
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("COMMIT前チェック", result.stdout)

    def test_commit_word_inside_quotes_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "echo 'git commit -m x'"}})
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestVerifyBeforeCommitExtensions(unittest.TestCase):
    """main/master 警告・staged 差分のシークレット検出・sandbox 非 ASCII 警告。"""

    def _run_in_repo(self, repo: Path, command: str) -> subprocess.CompletedProcess:
        json_input = json.dumps({"tool_input": {"command": command}})
        return _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input, cwd=str(repo))

    def test_main_branch_commit_gets_recovery_procedure_warning(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="main")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("main/master", result.stdout)
        self.assertIn("git push origin HEAD:refs/heads/", result.stdout)

    def test_feature_branch_commit_has_no_recovery_procedure_warning(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("main/master", result.stdout)

    def test_sandbox_cwd_with_non_ascii_message_warns(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        sandbox_dir = repo / "sandbox" / "proj"
        sandbox_dir.mkdir(parents=True)
        json_input = json.dumps({"tool_input": {"command": 'git commit -m "日本語のコミット"'}})
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input, cwd=str(sandbox_dir))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("非 ASCII", result.stdout)

    def test_non_sandbox_cwd_with_non_ascii_message_does_not_warn(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        json_input = json.dumps({"tool_input": {"command": 'git commit -m "日本語のコミット"'}})
        result = _run(VERIFY_BEFORE_COMMIT_HOOK, input_text=json_input, cwd=str(repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("非 ASCII", result.stdout)


class TestBlockSecretsInCommit(unittest.TestCase):
    """staged 差分のシークレット検出（deny）。

    verify-before-commit から分離した hook。あちらは Claude の additionalContext 注入が
    目的で claude / codex 限定だが、この deny 判定は runtime 非依存なので全 runtime に配る。
    """

    def _run_in_repo(self, repo: Path, command: str) -> subprocess.CompletedProcess:
        json_input = json.dumps({"tool_input": {"command": command}})
        return _run(BLOCK_SECRETS_IN_COMMIT_HOOK, input_text=json_input, cwd=str(repo))

    def test_staged_aws_key_is_blocked_with_file_and_line(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "secret.txt").write_text("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
        subprocess.run(["git", "-C", str(repo), "add", "secret.txt"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 2)
        self.assertIn("secret.txt:1", result.stderr)

    def test_staged_private_key_is_blocked(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n")
        subprocess.run(["git", "-C", str(repo), "add", "id_rsa"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 2)
        self.assertIn("id_rsa:1", result.stderr)

    def test_staged_github_token_is_blocked(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "conf.env").write_text(
            "GITHUB_TOKEN=ghp_" + "a" * 36 + "\n"
        )
        subprocess.run(["git", "-C", str(repo), "add", "conf.env"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 2)

    def test_staged_anthropic_key_is_blocked(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "conf.env").write_text("ANTHROPIC_API_KEY=sk-ant-" + "a" * 24 + "\n")
        subprocess.run(["git", "-C", str(repo), "add", "conf.env"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 2)

    def test_normal_staged_diff_is_not_blocked(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "app.py").write_text("print('hello world')\n")
        subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_non_commit_command_is_ignored(self):
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "secret.txt").write_text("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
        subprocess.run(["git", "-C", str(repo), "add", "secret.txt"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git status")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_add_and_commit_in_one_command_is_blocked(self):
        """PreToolUse は add の実行前に走るので、同一コマンドの add は検査を空振りさせる。

        `git add secret.txt && git commit` を素通しすると、hook が空の index を見て
        allow したあとにシークレットごと commit される（Codex review P1）。
        """
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "secret.txt").write_text("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
        result = self._run_in_repo(repo, "git add secret.txt && git commit -m update")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("別々のコマンド", result.stderr)

    def test_commit_dash_a_is_blocked(self):
        """`git commit -a` は commit 時に stage するので、index を見る検査が取りこぼす。"""
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        result = self._run_in_repo(repo, "git commit -a -m update")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("git add", result.stderr)

    def test_commit_dash_am_combined_flag_is_blocked(self):
        """結合短フラグ（-am）も同じ穴。"""
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        result = self._run_in_repo(repo, 'git commit -am "update"')
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_plain_commit_is_not_treated_as_commit_dash_a(self):
        """-m だけの通常の commit を -a 検出で誤爆させない。"""
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "app.py").write_text("print('hello')\n")
        subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True, capture_output=True)
        result = self._run_in_repo(repo, 'git commit -m "update"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_unresolvable_target_is_blocked(self):
        """`git -C $PWD commit` は hook 側で未展開のまま渡る。allow に倒すと検査を回避できる。"""
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        result = self._run_in_repo(repo, "git -C $PWD commit -m update")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("解決できませんでした", result.stderr)

    def test_hook_source_does_not_self_match_its_own_secret_patterns(self):
        """このスクリプト自身や danger-rules.json のパターン文字列を staged しても block しない。"""
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)

        shutil.copy2(BLOCK_SECRETS_IN_COMMIT_HOOK, repo / "block-secrets-in-commit.sh")
        shutil.copy2(
            REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json",
            repo / "danger-rules.json",
        )
        subprocess.run(
            ["git", "-C", str(repo), "add", "block-secrets-in-commit.sh", "danger-rules.json"],
            check=True, capture_output=True,
        )
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_added_line_starting_with_double_plus_is_still_scanned(self):
        """diff の追加行が `++i; // ghp_...` のように `+++` から始まっても、真の
        `+++ b/<file>` ヘッダー行と誤認してスキップしない（次にスペースを要求する）。
        """
        repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-x")
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        (repo / "counter.c").write_text("++i; // ghp_" + "a" * 36 + "\n")
        subprocess.run(["git", "-C", str(repo), "add", "counter.c"], check=True, capture_output=True)
        result = self._run_in_repo(repo, "git commit -m update")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("counter.c:1", result.stderr)


class TestVerifyBeforeCommitTargetResolution(unittest.TestCase):
    """commit を打つ対象 repo を CMD 文字列から解決する（cwd と対象 repo が異なる形）。"""

    def _stage_secret(self, repo: Path) -> None:
        (repo / "secret.txt").write_text("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "secret.txt"], check=True, capture_output=True
        )

    def test_git_dash_c_target_resolves_to_target_repo(self):
        target_repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-target")
        self.addCleanup(shutil.rmtree, target_repo.parent, ignore_errors=True)
        self._stage_secret(target_repo)

        cwd_repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-cwd")
        self.addCleanup(shutil.rmtree, cwd_repo.parent, ignore_errors=True)

        json_input = json.dumps(
            {"tool_input": {"command": f"git -C {target_repo} commit -m update"}}
        )
        result = _run(BLOCK_SECRETS_IN_COMMIT_HOOK, input_text=json_input, cwd=str(cwd_repo))
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("secret.txt:1", result.stderr)

    def test_cd_and_commit_target_resolves_to_target_repo(self):
        target_repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-target")
        self.addCleanup(shutil.rmtree, target_repo.parent, ignore_errors=True)
        self._stage_secret(target_repo)

        cwd_repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-cwd")
        self.addCleanup(shutil.rmtree, cwd_repo.parent, ignore_errors=True)

        json_input = json.dumps(
            {"tool_input": {"command": f"cd {target_repo} && git commit -m update"}}
        )
        result = _run(BLOCK_SECRETS_IN_COMMIT_HOOK, input_text=json_input, cwd=str(cwd_repo))
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("secret.txt:1", result.stderr)

    def test_no_cd_or_dash_c_falls_back_to_cwd(self):
        cwd_repo = _make_git_repo(Path(tempfile.mkdtemp()), branch="feature-cwd")
        self.addCleanup(shutil.rmtree, cwd_repo.parent, ignore_errors=True)
        self._stage_secret(cwd_repo)

        json_input = json.dumps({"tool_input": {"command": "git commit -m update"}})
        result = _run(BLOCK_SECRETS_IN_COMMIT_HOOK, input_text=json_input, cwd=str(cwd_repo))
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("secret.txt:1", result.stderr)


class TestVerifyBeforePush(unittest.TestCase):
    """PreToolUse:Bash。push コマンドに additionalContext のリマインドを付与する
    （実際に exit 2 でブロックする挙動は無い。advisory-only hook）。
    """

    def test_git_push_command_gets_reminder(self):
        json_input = json.dumps({"tool_input": {"command": "git push origin main"}})
        result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text=json_input)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("PUSH前チェック", result.stdout)

    def test_unrelated_command_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text=json_input)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_input_without_trigger_word_is_noop(self):
        result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text="totally unrelated garbage")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_input_with_trigger_word_does_not_crash(self):
        """'push' を含む不正な JSON でも fail-open で exit 0（jq パースエラーで crash しない）。"""
        result = _run(
            VERIFY_BEFORE_PUSH_HOOK, input_text="not valid json but has push word"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def _push_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
        )
        return repo

    def test_uncommitted_files_are_listed_in_the_reminder(self):
        """未 commit の変更を push 直前に実物として提示する。

        commit 漏れのまま push され、CI が落ちてから気づいた実例があるため、
        「確認したか」の問いかけではなくファイル名そのものを出す。
        """
        json_input = json.dumps({"tool_input": {"command": "git push origin HEAD"}})
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._push_repo(Path(tmp))
            (repo / "forgotten.txt").write_text("wip\n", encoding="utf-8")

            result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text=json_input, cwd=str(repo))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("forgotten.txt", result.stdout)
        self.assertIn("未 commit", result.stdout)

    def test_dirty_files_of_a_different_repo_are_not_listed(self):
        """`cd repo-b && git push` を repo A から実行しても repo A の変更は出さない。

        hook 自体の cwd は repo A のままなので、対象 repo を解決せずに status を
        読むと push 対象ではない repo のファイル名を「この PR に含めるべきか」と
        警告することになる（2026-09-05 の Codex review P2）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_a = self._push_repo(root)
            (repo_a / "unrelated-in-repo-a.txt").write_text("noise\n", encoding="utf-8")

            repo_b_parent = root / "b"
            repo_b_parent.mkdir()
            repo_b = self._push_repo(repo_b_parent)

            json_input = json.dumps(
                {"tool_input": {"command": f"cd {repo_b} && git push origin HEAD"}}
            )
            result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text=json_input, cwd=str(repo_a))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("unrelated-in-repo-a.txt", result.stdout)

    def test_clean_tree_has_no_uncommitted_warning(self):
        """クリーンな作業ツリーでは未 commit 警告を出さない（常時警告で麻痺させない）。"""
        json_input = json.dumps({"tool_input": {"command": "git push origin HEAD"}})
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._push_repo(Path(tmp))

            result = _run(VERIFY_BEFORE_PUSH_HOOK, input_text=json_input, cwd=str(repo))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PUSH前チェック", result.stdout)
        self.assertNotIn("未 commit", result.stdout)


if __name__ == "__main__":
    unittest.main()

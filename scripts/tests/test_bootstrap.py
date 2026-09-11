#!/usr/bin/env python3
"""bootstrap.sh の引数分岐テスト。

本物の bootstrap.sh + フェイク distribute.py（呼び出し引数を JSON Lines でログするだけ）
を使い、実際の引数パース・ループ順序・core.hooksPath 設定を検証する。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from tests._helpers import make_bootstrap_repo  # noqa: E402


def run_bootstrap(
    repo: Path,
    call_log: Path,
    *args: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["BOOTSTRAP_CALL_LOG"] = str(call_log)
    env["CODEX_HOME"] = str(repo.parent / ".codex-home")
    # Fixture repoにはmise.tomlがないため、bootstrap本体と同じinterpreterを明示する。
    # 実テストはmise管理Python 3.14.7で起動される。
    env["PYTHON_BIN"] = sys.executable
    # Step 1.5 (global mise env 確認) が実機の ~/.config/mise/config.toml を読まないよう、
    # 既定では存在しない一時パスに固定する（テスト間で決定的な drift 表示にする）。
    env.setdefault("MISE_GLOBAL_CONFIG", str(repo.parent / "mise-global-config-missing.toml"))
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "bootstrap.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        # stdin を明示的に非 tty にし、対話プロンプト分岐（.env / config.local.toml 生成）を
        # 常に非対話経路に固定する。テスト環境の実際の stdin がtty かどうかに依存させない。
        stdin=subprocess.DEVNULL,
    )


class BootstrapTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = make_bootstrap_repo(self.root)
        self.call_log = self.root / "calls.log"

    def tearDown(self):
        self._tmp.cleanup()

    def calls(self) -> list[dict]:
        if not self.call_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def hooks_path(self) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


class TestBootstrapNoArgs(BootstrapTestCase):
    def test_calls_distribute_for_all_default_targets_in_order(self):
        result = run_bootstrap(self.repo, self.call_log)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(
            [c["argv"][0] for c in calls],
            ["shared-agents", "claude", "codex", "opencode", "opencode-launcher", "pi", "omp"],
        )
        for c in calls:
            self.assertEqual(c["argv"][1], "--push")
            self.assertIn("--repo-root", c["argv"])
            repo_root_idx = c["argv"].index("--repo-root")
            self.assertEqual(
                os.path.realpath(c["argv"][repo_root_idx + 1]), os.path.realpath(str(self.repo))
            )
            self.assertNotIn("--dry-run", c["argv"])


class TestBootstrapTargetsFlag(BootstrapTestCase):
    def test_targets_with_space_form_and_comma_list(self):
        result = run_bootstrap(self.repo, self.call_log, "--targets", "claude,codex")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual([c["argv"][0] for c in calls], ["claude", "codex"])


class TestBootstrapTargetsEqualsForm(BootstrapTestCase):
    def test_targets_equals_form_parses_single_target(self):
        result = run_bootstrap(self.repo, self.call_log, "--targets=opencode")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual([c["argv"][0] for c in calls], ["opencode"])


class TestBootstrapDryRun(BootstrapTestCase):
    def test_dry_run_flag_propagates_to_distribute(self):
        result = run_bootstrap(self.repo, self.call_log, "--dry-run")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 7)
        for c in calls:
            self.assertIn("--dry-run", c["argv"])


class TestBootstrapUnknownArg(BootstrapTestCase):
    def test_unknown_argument_exits_nonzero_without_calling_distribute(self):
        result = run_bootstrap(self.repo, self.call_log, "--bogus")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: unknown argument: --bogus", result.stderr)
        self.assertEqual(self.calls(), [])


class TestBootstrapCoreHooksPath(BootstrapTestCase):
    def test_sets_core_hooks_path_on_push(self):
        self.assertEqual(self.hooks_path(), "")

        result = run_bootstrap(self.repo, self.call_log)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.hooks_path(), ".githooks")


class TestBootstrapDryRunGitConfig(BootstrapTestCase):
    def test_dry_run_should_not_mutate_git_config(self):
        """--dry-run では core.hooksPath を実際に書き込まない（Step 3 が DRY_RUN_FLAG を尊重）。"""
        result = run_bootstrap(self.repo, self.call_log, "--dry-run")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotEqual(
            self.hooks_path(),
            ".githooks",
            "dry-run なのに core.hooksPath が実際に設定されてしまっている",
        )
        self.assertIn("would set core.hooksPath", result.stdout)


class TestBootstrapSkipSubmodule(BootstrapTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # with_extras=False: このクラスは extras 未取得時の分岐（--skip-submodule /
        # fail-close / --core-only）自体を検証するため、extras を意図的に作らない。
        self.repo = make_bootstrap_repo(self.root, with_gitmodules=True, with_extras=False)
        self.call_log = self.root / "calls.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_skip_submodule_flag_prevents_extras_resolution(self):
        result = run_bootstrap(self.repo, self.call_log, "--skip-submodule")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("--skip-submodule 指定", combined)
        self.assertNotIn("extras が見つからない", combined)

    def test_without_extras_and_default_fails_closed(self):
        result = run_bootstrap(self.repo, self.call_log)

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ERROR", combined)
        self.assertIn("extras が見つからない", combined)
        self.assertIn("git submodule update --init packages/extras/_active", combined)
        self.assertIn("--core-only", combined)
        # distribute.py には到達しない（fail-close で早期終了）
        self.assertEqual(self.calls(), [])

    def test_core_only_flag_allows_missing_extras(self):
        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("extras が見つからない。core のみで配布を続行（--core-only 指定）", combined)

    def test_with_extras_dir_reports_available(self):
        extras = self.repo / "packages" / "extras" / "_active"
        extras.mkdir(parents=True)
        (extras / "rules").mkdir()

        result = run_bootstrap(self.repo, self.call_log)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("extras 利用可能", combined)


class TestBootstrapWithoutExtrasDeclaration(BootstrapTestCase):
    """extras を宣言しない配布（public slim 等）では fail-close せず skip して配布を続ける。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = make_bootstrap_repo(self.root, with_gitmodules=False, with_extras=False)
        self.call_log = self.root / "calls.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_declaration_skips_instead_of_failing(self):
        result = run_bootstrap(self.repo, self.call_log)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("extras は宣言されていない", combined)
        self.assertNotIn("ERROR", combined)
        # fail-close と違い distribute.py まで到達する
        self.assertNotEqual(self.calls(), [])


class TestBootstrapEnvSetup(BootstrapTestCase):
    """.env の対話生成は非対話経路のみ検証する（tty 分岐は run_bootstrap の DEVNULL 固定で常に非対話）。"""

    def test_env_missing_and_noninteractive_warns_and_does_not_create_file(self):
        env_file = self.repo / ".env"
        self.assertFalse(env_file.exists())

        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn(".env が見つかりません（非対話のためスキップ）", combined)
        self.assertFalse(env_file.exists())

    def test_env_present_is_left_untouched(self):
        env_file = self.repo / ".env"
        env_file.write_text("BLOCKED_TERMS=existing-term\n", encoding="utf-8")

        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(env_file.read_text(encoding="utf-8"), "BLOCKED_TERMS=existing-term\n")

    def test_gitignore_gets_env_entry_when_missing(self):
        gitignore = self.repo / ".gitignore"
        self.assertFalse(gitignore.exists())

        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(".env", gitignore.read_text(encoding="utf-8").splitlines())

    def test_gitignore_not_duplicated_when_already_present(self):
        gitignore = self.repo / ".gitignore"
        gitignore.write_text(".env\nother-entry\n", encoding="utf-8")

        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(gitignore.read_text(encoding="utf-8"), ".env\nother-entry\n")


class TestBootstrapCoreHooksPathCustomValue(BootstrapTestCase):
    def test_does_not_overwrite_existing_custom_hooks_path(self):
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "core.hooksPath", "some-custom-hooks"],
            check=True,
            capture_output=True,
        )

        result = run_bootstrap(self.repo, self.call_log, "--core-only")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.hooks_path(), "some-custom-hooks")
        combined = result.stdout + result.stderr
        self.assertIn("core.hooksPath は既に 'some-custom-hooks' に設定されています", combined)

class TestBootstrapCodexSetup(BootstrapTestCase):
    def test_does_not_provision_luna_catalog(self):
        codex_home = self.root / "codex-home"
        codex_home.mkdir()
        (codex_home / "models_cache.json").write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "slug": "gpt-5.6-luna",
                            "default_reasoning_level": "medium",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = run_bootstrap(
            self.repo,
            self.call_log,
            "--targets",
            "codex",
            "--core-only",
            env_overrides={"CODEX_HOME": str(codex_home)},
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertFalse((codex_home / "harunon-model-catalog.json").exists())
        self.assertFalse(
            (self.repo / "packages" / "targets" / "codex" / "config.local.toml").exists()
        )

    def test_interactive_setup_recognizes_indented_sandbox_table(self):
        local_config = self.repo / "packages" / "targets" / "codex" / "config.local.toml"
        local_config.parent.mkdir(parents=True)
        local_config.write_text(
            " [sandbox_workspace_write]\nwritable_roots = []\n",
            encoding="utf-8",
        )
        import errno
        import pty

        env = dict(os.environ)
        env["BOOTSTRAP_CALL_LOG"] = str(self.call_log)
        # run_bootstrap と同じ理由（fixture repo に mise.toml が無い）で interpreter を明示する
        env["PYTHON_BIN"] = sys.executable
        command = [
            "/bin/bash",
            str(self.repo / "scripts" / "bootstrap.sh"),
            "--targets",
            "codex",
            "--core-only",
        ]
        pid, master_fd = pty.fork()
        if pid == 0:
            os.execve("/bin/bash", command, env)

        input_data = f"\n{self.root / 'worktrees'}\n{self.repo / '.git'}\n".encode()
        output = bytearray()
        try:
            offset = 0
            while offset < len(input_data):
                offset += os.write(master_fd, input_data[offset:])
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
        finally:
            os.close(master_fd)
        _, status = os.waitpid(pid, 0)
        returncode = os.waitstatus_to_exitcode(status)

        self.assertEqual(returncode, 0, msg=output.decode(errors="replace"))
        self.assertEqual(
            local_config.read_text(encoding="utf-8").count("[sandbox_workspace_write]"),
            1,
        )

class TestBootstrapRulesyncInstall(BootstrapTestCase):
    """Step 1.75: 外部 skill (rulesync) の取得を検証する（ADR-011 Update 2026-08-30）。

    実際の配置・ledger 管理は distribute.py（resolver の CURATED_SKILLS_SOURCE 統合）が
    担うため、ここでは bootstrap.sh が push 前に `rulesync install --frozen` を
    fail-closed で呼ぶことだけを検証する（distribute.py はフェイクなので実配置は見ない）。
    """

    def setUp(self):
        super().setUp()
        (self.repo / "rulesync.lock").write_text("{}", encoding="utf-8")
        self.stub_bin = self.root / "stub-bin"
        self.stub_bin.mkdir()
        for name in ("mise", "gh"):
            stub = self.stub_bin / name
            stub.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            stub.chmod(0o755)

    def _write_stub(self, name: str, body: str) -> None:
        stub = self.stub_bin / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        environment = {"PATH": f"{self.stub_bin}:{os.environ['PATH']}"}
        return run_bootstrap(
            self.repo, self.call_log, "--targets", "claude", *args, env_overrides=environment
        )

    def test_rulesync_install_runs_before_target_push(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("rulesync install --frozen", result.stdout)

    def test_rulesync_install_failure_fails_closed(self):
        # 常駐ルールが /tdd・/diagnosing-bugs を名指し参照するため、取得失敗を通さない
        self._write_stub("mise", "#!/bin/bash\nexit 1\n")

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("rulesync install --frozen 失敗", combined)

    def test_dry_run_does_not_invoke_rulesync(self):
        result = self._run("--dry-run")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("dry-run: would run 'rulesync install --frozen'", result.stdout)

    def test_no_lockfile_skips_rulesync_install(self):
        (self.repo / "rulesync.lock").unlink()
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotIn("Step 1.75", result.stdout)


class TestBootstrapCheckMode(BootstrapTestCase):
    """--check は drift（exit 1）とエラー（それ以外）を区別し、非ゼロで `✓` を出さない。"""

    def test_clean_check_prints_ok(self):
        result = run_bootstrap(self.repo, self.call_log, "--check", "--targets", "claude")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("✓ check claude", result.stdout)

    def test_drift_is_reported_without_ok_and_exits_one(self):
        result = run_bootstrap(
            self.repo, self.call_log, "--check", "--targets", "claude",
            env_overrides={"FAKE_DISTRIBUTE_EXIT": "1"},
        )
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertNotIn("✓ check claude", result.stdout)
        self.assertIn("drift あり", result.stdout)

    def test_internal_error_is_reported_as_error(self):
        result = run_bootstrap(
            self.repo, self.call_log, "--check", "--targets", "claude",
            env_overrides={"FAKE_DISTRIBUTE_EXIT": "2"},
        )
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertNotIn("✓ check claude", result.stdout)
        self.assertIn("ERROR: check claude failed", result.stderr)


class TestBootstrapGlobalMiseEnvCheck(BootstrapTestCase):
    """Step 1.5: global mise env 確認は report-only（push/check どちらも通す）。"""

    def _matching_config(self) -> Path:
        cfg = self.root / "matching-mise-config.toml"
        cfg.write_text(
            '[tools]\npnpm = "11.20.0"\n"npm:@earendil-works/pi-coding-agent" = "0.84.3"\n'
            '"npm:@oh-my-pi/pi-coding-agent" = "18.0.8"\n"npm:@jackwener/opencli" = "1.8.6"\n'
            '"npm:difit" = "5.0.9"\n"npm:@alibaba-group/open-code-review" = "1.1.10"\n'
            '"npm:omniroute" = "3.8.49"\nprek = "0.4.12"\n\n'
            '[env]\nPI_FFF_MODE = "override"\n',
            encoding="utf-8",
        )
        return cfg

    def test_push_mode_warns_on_drift(self):
        drifted = self.root / "drifted-mise-config.toml"
        drifted.write_text('[tools]\npnpm = "11.20.0"\n', encoding="utf-8")

        result = run_bootstrap(
            self.repo, self.call_log, "--targets", "claude",
            env_overrides={"MISE_GLOBAL_CONFIG": str(drifted)},
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("Step 1.5: global mise env 確認", combined)
        self.assertIn("global mise の [env] が SSOT とズレています", combined)
        # 実物の example をコピーした fixture なので、宣言済み tool の欠落が drift として出る
        self.assertIn("tool 未インストール", combined)

    def test_push_mode_clean_shows_no_warning(self):
        result = run_bootstrap(
            self.repo, self.call_log, "--targets", "claude",
            env_overrides={"MISE_GLOBAL_CONFIG": str(self._matching_config())},
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("global mise: 宣言どおり", combined)
        self.assertNotIn("global mise の [env] が SSOT とズレています", combined)

    def test_check_mode_warns_on_drift(self):
        drifted = self.root / "drifted-mise-config.toml"
        drifted.write_text('[tools]\npnpm = "11.20.0"\n', encoding="utf-8")

        result = run_bootstrap(
            self.repo, self.call_log, "--check", "--targets", "claude",
            env_overrides={"MISE_GLOBAL_CONFIG": str(drifted)},
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("global mise の [env] が SSOT とズレています", combined)

    def test_step_never_forces_bootstrap_failure(self):
        """drift だけでは overall_rc に影響しない（--check の drift 判定は distribute 由来のみ）。"""
        drifted = self.root / "drifted-mise-config.toml"
        drifted.write_text('[tools]\npnpm = "11.20.0"\n', encoding="utf-8")

        result = run_bootstrap(
            self.repo, self.call_log, "--check", "--targets", "claude",
            env_overrides={"MISE_GLOBAL_CONFIG": str(drifted)},
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("✓ check claude", result.stdout)


class TestCodexLocalConfigWriter(unittest.TestCase):
    """codex-local-config.py: 入力パスを TOML basic string としてエスケープし、不正値は拒否する。"""

    SCRIPT = REPO_ROOT / "scripts" / "codex-local-config.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *args], capture_output=True, text=True, timeout=30
        )

    def test_quotes_and_backslashes_are_escaped_into_valid_toml(self):
        import tomllib

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.local.toml"
            cfg.write_text("model = \"x\"\n", encoding="utf-8")
            result = self._run(str(cfg), '/wt/we"ird\\path', "/repo/.git", "/Users/me")
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = tomllib.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "x")
            self.assertEqual(
                data["sandbox_workspace_write"]["writable_roots"][:2],
                ['/wt/we"ird\\path', "/repo/.git"],
            )

    def test_relative_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.local.toml"
            result = self._run(str(cfg), "relative/wt", "/repo/.git", "/Users/me")
            self.assertEqual(result.returncode, 1)
            self.assertIn("絶対パス", result.stderr)
            self.assertFalse(cfg.exists())

    def test_newline_in_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.local.toml"
            result = self._run(str(cfg), "/wt\nmodel = 'evil'", "/repo/.git", "/Users/me")
            self.assertEqual(result.returncode, 1)
            self.assertFalse(cfg.exists())


class TestBootstrapCodexPluginStep(BootstrapTestCase):
    """Step 1.9（harunon-core plugin の Codex 配備）のゲート。

    plugins/cache と config.toml の [plugins.*] は Codex がアプリ管理する領域なので、
    ファイルコピーではなく Codex CLI 自身に入れさせる。guard の配備であって配布物の
    整合ではないため、失敗しても bootstrap 全体は止めない。
    """

    def _path_with_fake_codex(self) -> str:
        """codex を持たない環境（CI）でも dry-run 分岐へ到達させる。

        Step 1.9 は codex CLI の有無を先に見るので、stub を置かないと CI では
        「CLI が無いためスキップ」に落ちて dry-run の挙動を検証できない。
        """
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir(exist_ok=True)
        stub = fake_bin / "codex"
        stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        return f"{fake_bin}:{os.environ['PATH']}"

    def test_dry_run_announces_without_touching_codex(self):
        result = run_bootstrap(
            self.repo,
            self.call_log,
            "--targets",
            "codex",
            "--dry-run",
            env_overrides={"PATH": self._path_with_fake_codex()},
        )

        self.assertIn("Step 1.9", result.stdout)
        self.assertIn("would build", result.stdout)
        self.assertNotIn("配備しました", result.stdout)

    def test_step_is_skipped_for_other_targets(self):
        result = run_bootstrap(self.repo, self.call_log, "--targets", "claude", "--dry-run")

        self.assertNotIn("Step 1.9", result.stdout)

    def test_missing_codex_cli_does_not_fail_the_run(self):
        """Codex 未導入のマシンで他ターゲットの配布まで巻き添えにしない。"""
        result = run_bootstrap(
            self.repo,
            self.call_log,
            "--targets",
            "codex",
            # codex は ~/.local/bin 等にあるので、システム標準だけの PATH にすると
            # bash / git は残したまま codex だけ見えなくなる
            env_overrides={"PATH": "/usr/bin:/bin"},
        )

        self.assertIn("codex CLI が無いため", result.stdout)


if __name__ == "__main__":
    unittest.main()

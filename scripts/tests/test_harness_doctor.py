#!/usr/bin/env python3
"""harness-doctor.sh のテスト。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "scripts" / "harness-doctor.sh"


def _build_minimal_path(tmp_dir: Path, include: list) -> str:
    """include に列挙したツールだけを symlink した bin dir を作り、その PATH 文字列を返す。

    システム PATH をそのまま使うと「あるツールだけ無いふり」ができないため、
    実バイナリへの symlink だけを集めた狭い PATH に差し替える。
    """
    bin_dir = tmp_dir / "minimal_bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in include:
        real = shutil.which(tool)
        if real is None:
            raise RuntimeError(f"test environment is missing required tool: {tool}")
        link = bin_dir / tool
        if not link.exists():
            link.symlink_to(real)
    return str(bin_dir)


class HarnessDoctorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fake_repo = self.root / "fake_repo"
        self.scripts_dir = self.fake_repo / "scripts"
        self.scripts_dir.mkdir(parents=True)
        shutil.copy(str(DOCTOR), str(self.scripts_dir / "harness-doctor.sh"))
        # Step 0.6 (global mise env) は本物の mise-global-check.py / harness_lib を呼ぶ。
        # fixture の $REPO_ROOT (=fake_repo) 直下に mise.global.example.toml が無いと
        # ENOENT で exit 2 になるため、本物一式をコピーする。live 側は実機の
        # ~/.config/mise/config.toml を読まないよう常に存在しないパスに固定する。
        # harness_lib は unmanaged_skills.py 等ほかの Step も同じディレクトリに置くため、
        # ここでは mise_global.py だけをピンポイントでコピーする（丸ごとコピーすると
        # Step 0.5 の unmanaged_skills.py まで fixture に紛れ込み、この fixture が
        # 想定していない未管理スキル判定が意図せず有効になってしまう）。
        harness_lib_dir = self.scripts_dir / "harness_lib"
        harness_lib_dir.mkdir(exist_ok=True)
        init_file = harness_lib_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
        shutil.copy(
            str(REPO_ROOT / "scripts" / "harness_lib" / "mise_global.py"),
            str(harness_lib_dir / "mise_global.py"),
        )
        shutil.copy(
            str(REPO_ROOT / "scripts" / "mise-global-check.py"),
            str(self.scripts_dir / "mise-global-check.py"),
        )
        shutil.copy(
            str(REPO_ROOT / "mise.global.example.toml"),
            str(self.fake_repo / "mise.global.example.toml"),
        )
        self.log_file = self.root / "calls.log"
        self._write_fake_validate(exit_code=0)
        self._write_fake_bootstrap(exit_code=0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_fake_validate(self, exit_code: int) -> None:
        (self.scripts_dir / "validate-harness.py").write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import sys\n"
            "with open(os.environ['DOCTOR_CALL_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write('validate ' + ' '.join(sys.argv[1:]) + '\\n')\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )

    def _write_fake_bootstrap(self, exit_code: int) -> None:
        (self.scripts_dir / "bootstrap.sh").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'bootstrap %s\\n' \"$*\" >> \"$DOCTOR_CALL_LOG\"\n"
            f"exit {exit_code}\n",
            encoding="utf-8",
        )

    def run_doctor(
        self,
        *args: str,
        path_override: str = None,
        home_override: Path = None,
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["DOCTOR_CALL_LOG"] = str(self.log_file)
        # doctor.sh はmise解決の絶対パスを使う。テストでは実行中の同じinterpreterを渡す。
        env["PYTHON_BIN"] = sys.executable
        # Step 0.6 (global mise env) が実機の ~/.config/mise/config.toml を読まないよう固定。
        env.setdefault("MISE_GLOBAL_CONFIG", str(self.root / "mise-global-config-missing.toml"))
        if path_override is not None:
            env["PATH"] = path_override
        if home_override is not None:
            env["HOME"] = str(home_override)
        return subprocess.run(
            ["bash", str(self.scripts_dir / "harness-doctor.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def calls(self) -> list[str]:
        if not self.log_file.exists():
            return []
        return self.log_file.read_text(encoding="utf-8").splitlines()


class TestHarnessDoctor(HarnessDoctorTestCase):
    def test_runs_meta_and_drift_checks_by_default(self):
        result = self.run_doctor()

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            self.calls(),
            [
                "validate --repo-root " + str(self.fake_repo),
                "bootstrap --check",
            ],
        )
        self.assertIn("harness healthy", result.stdout)

    def test_meta_only_skips_drift_check_and_forwards_json(self):
        result = self.run_doctor("--meta-only", "--json")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            self.calls(),
            ["validate --repo-root " + str(self.fake_repo) + " --json"],
        )

    def test_drift_only_skips_meta_check_and_forwards_targets(self):
        result = self.run_doctor("--drift-only", "--targets", "claude,codex")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            self.calls(),
            ["bootstrap --check --targets claude,codex"],
        )

    def test_keeps_running_drift_check_after_meta_failure(self):
        self._write_fake_validate(exit_code=1)

        result = self.run_doctor()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.calls(),
            [
                "validate --repo-root " + str(self.fake_repo),
                "bootstrap --check",
            ],
        )
        self.assertIn("issues found", result.stdout)

    def test_returns_friendly_error_when_targets_value_is_missing(self):
        result = self.run_doctor("--targets")

        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR: --targets requires a value", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_help_prints_usage(self):
        result = self.run_doctor("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--meta-only", result.stdout)


class TestHarnessDoctorUnmanagedSkills(HarnessDoctorTestCase):
    """Step 0.5: 未管理スキルは doctor が FAIL にする（pre-push は警告のみ）。"""

    def setUp(self):
        super().setUp()
        # 基底 setUp が Step 0.6 用に harness_lib/mise_global.py だけを先に置いているので、
        # ここでは本物一式で上書きする（Step 0.5 の unmanaged_skills.py を実際に使う）。
        shutil.rmtree(str(self.scripts_dir / "harness_lib"))
        shutil.copytree(
            str(REPO_ROOT / "scripts" / "harness_lib"),
            str(self.scripts_dir / "harness_lib"),
        )
        (self.fake_repo / "packages" / "core" / "skills" / "core-skill").mkdir(parents=True)
        (self.fake_repo / "packages" / "extras" / "_active" / "skills").mkdir(parents=True)
        self.claude_dir = self.root / "claude"
        (self.claude_dir / "skills").mkdir(parents=True)
        self.agents_dir = self.root / "agents-skills"
        self.agents_dir.mkdir()

    def run_doctor_with_skills(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["DOCTOR_CALL_LOG"] = str(self.log_file)
        env["PYTHON_BIN"] = sys.executable
        env["CLAUDE_DIR"] = str(self.claude_dir)
        env["AGENTS_SKILLS_DIR"] = str(self.agents_dir)
        return subprocess.run(
            ["bash", str(self.scripts_dir / "harness-doctor.sh"), "--skip-prereq"],
            env=env, capture_output=True, text=True, timeout=30,
        )

    def test_fails_when_live_skill_is_undeclared(self):
        (self.agents_dir / "npx-installed").mkdir()

        result = self.run_doctor_with_skills()

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("Step 0.5", result.stdout)
        self.assertIn("未管理スキルあり", result.stdout)
        self.assertIn("npx-installed", result.stdout)
        self.assertIn("unmanaged-skills-allowlist.json", result.stdout)
        # 後続の meta / drift チェックは止めずに実行する
        self.assertEqual(len(self.calls()), 2)

    def test_passes_when_all_live_skills_are_managed(self):
        (self.claude_dir / "skills" / "core-skill").mkdir()

        result = self.run_doctor_with_skills()

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("未管理スキルなし", result.stdout)

    def test_warns_only_when_extras_submodule_is_uninitialized(self):
        shutil.rmtree(self.fake_repo / "packages" / "extras")
        (self.agents_dir / "maybe-extras").mkdir()

        result = self.run_doctor_with_skills()

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("判定不能", result.stdout)
        self.assertIn("maybe-extras", result.stdout)


class TestHarnessDoctorPrerequisites(HarnessDoctorTestCase):
    def test_fails_when_required_tool_missing(self):
        path = _build_minimal_path(
            self.root, ["bash", "dirname", "git", "python3", "perl", "shasum"]
        )

        result = self.run_doctor(path_override=path)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("jq が見つかりません（必須）", result.stdout)

    def test_warns_but_passes_when_recommended_tool_missing(self):
        path = _build_minimal_path(
            self.root, ["bash", "dirname", "git", "python3", "jq", "perl", "shasum"]
        )

        result = self.run_doctor(path_override=path)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("shellcheck が見つかりません（推奨）", result.stdout)
        self.assertIn("rtk が見つかりません（推奨）", result.stdout)

    def test_skip_prereq_flag_skips_step0(self):
        result = self.run_doctor("--skip-prereq")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotIn("Step 0", result.stdout)

    def test_warns_on_missing_env_and_unconfigured_hooks_path(self):
        result = self.run_doctor()

        self.assertIn(".env が見つかりません", result.stdout)
        self.assertIn("core.hooksPath が .githooks ではありません", result.stdout)

    def test_ok_when_env_and_hooks_path_configured(self):
        (self.fake_repo / ".env").write_text("BLOCKED_TERMS=foo\n", encoding="utf-8")
        subprocess.run(["git", "init", str(self.fake_repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.fake_repo), "config", "core.hooksPath", ".githooks"],
            check=True,
            capture_output=True,
        )

        result = self.run_doctor()

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(".env: BLOCKED_TERMS 定義済み", result.stdout)
        self.assertIn("core.hooksPath: .githooks", result.stdout)

    def test_pi_auth_requires_openai_codex_entry(self):
        cases = (
            ("openai", '{"openai-codex":{"access":"redacted"}}', "openai-codex credential file present"),
            ("other-provider", '{"anthropic":{"access":"redacted"}}', "no openai-codex entry"),
            ("empty", "{}", "pi 初回セットアップ未了"),
        )
        for name, payload, expected in cases:
            with self.subTest(name=name):
                home = self.root / f"home-{name}"
                auth = home / ".pi" / "agent" / "auth.json"
                auth.parent.mkdir(parents=True)
                auth.write_text(payload, encoding="utf-8")

                result = self.run_doctor(home_override=home)

                self.assertIn(expected, result.stdout, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()


class TestHarnessDoctorCodexPlugin(HarnessDoctorTestCase):
    """codex plugin (harunon-core) の配備検知。

    bootstrap は plugins/ を配らない（Codex のアプリ管理状態）ので doctor が唯一の
    検知点になる。2026-07-12 の追加から 2026-09-05 まで未インストールのまま
    誰も気づかなかったため、3 状態を pin する。

    比較そのものは scripts/check-codex-plugin.py（テストは test_check_codex_plugin.py）
    に移した。ここで見るのは doctor がそれを呼び、出力と直し方を画面に出すことだけ。
    """

    def _write_fake_checker(self, exit_code: int, stdout: str) -> None:
        checker = self.scripts_dir / "check-codex-plugin.py"
        checker.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"print({stdout!r})\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )

    def _fake_home(self) -> Path:
        home = self.root / "fake_home"
        (home / ".codex").mkdir(parents=True, exist_ok=True)
        (home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
        return home

    def test_reports_checker_output_when_current(self):
        self._write_fake_checker(0, "codex plugin harunon-core: installed and current（0.1.2）")
        result = self.run_doctor("--meta-only", home_override=self._fake_home())

        self.assertIn("installed and current", result.stdout)
        self.assertNotIn("入れ直してください", result.stdout)

    def test_surfaces_drift_detail_and_how_to_fix(self):
        """乖離したら、どのファイルがずれているかと直し方の両方を出す。"""
        self._write_fake_checker(
            1,
            "codex plugin harunon-core が SSOT と乖離しています（0.1.2）:\n"
            "  - hooks/block-secrets-in-commit.sh: 配備されていません",
        )
        result = self.run_doctor("--meta-only", home_override=self._fake_home())

        self.assertIn("SSOT と乖離", result.stdout)
        self.assertIn("block-secrets-in-commit.sh: 配備されていません", result.stdout)
        # 検知しても次の行動が決まらないと意味がない
        self.assertIn("codex plugin add harunon-core@harunon-local", result.stdout)

    def test_surfaces_not_installed(self):
        self._write_fake_checker(1, "codex plugin harunon-core が未インストールです")
        result = self.run_doctor("--meta-only", home_override=self._fake_home())

        self.assertIn("harunon-core が未インストール", result.stdout)
        self.assertIn("codex plugin add harunon-core@harunon-local", result.stdout)

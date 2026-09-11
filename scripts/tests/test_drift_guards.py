#!/usr/bin/env python3
"""drift ガード（pre-push / bootstrap.sh）のフィクスチャテスト。

test_scan_new_skills.py の流儀（subprocess 実行 + tempfile フィクスチャ + unittest）を踏襲。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRE_PUSH = REPO_ROOT / ".githooks" / "pre-push"
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"

import sys
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from tests._helpers import copy_scripts_to_repo  # noqa: E402


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def run_pre_push(tmp_repo: Path, claude_dir: Path) -> subprocess.CompletedProcess:
    """tmp_repo 内で pre-push を実行する。"""
    env = dict(os.environ)
    env["CLAUDE_DIR"] = str(claude_dir)
    # GIT_DIR を設定しないと git rev-parse --show-toplevel が tmp_repo を返す
    return subprocess.run(
        ["bash", str(PRE_PUSH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_repo),
    )


def make_git_repo(path: Path) -> None:
    """最小限の git repo を作成する（commit は不要）。"""
    subprocess.run(
        ["git", "init", str(path)],
        check=True,
        capture_output=True,
    )
    # extras/_active がないと submodule チェックを素通りする（意図通り）


def make_core_file(repo: Path, rel: str, content: str) -> None:
    """packages/core/<rel> にファイルを作成する。"""
    target = repo / "packages" / "core" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def setup_pre_push_repo(repo: Path) -> None:
    """pre-push テスト用に必要な scripts/ + packages/targets/claude/config.json を設置する。

    新しい pre-push は distribute.py claude --check --live を呼ぶため、
    フィクスチャ repo に scripts/distribute.py + harness_lib/ + config.json が必要。
    """
    copy_scripts_to_repo(repo)

    # packages/targets/claude/config.json（distribute.py が参照する）
    claude_target_dir = repo / "packages" / "targets" / "claude"
    claude_target_dir.mkdir(parents=True, exist_ok=True)
    # configDir は存在しないパスでも --live オプションで上書きするため最低限の宣言だけ用意
    (claude_target_dir / "config.json").write_text(
        json.dumps({
            "name": "claude",
            "displayName": "Claude Code",
            "configDir": "~/.claude",
            "configFile": "settings.json",
            "instructionsFile": "CLAUDE.md",
            "distribute": {
                "CLAUDE.md": {"source": "packages/core/CLAUDE.md"},
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# pre-push ドリフト検出テスト
# ---------------------------------------------------------------------------

class PrePushDriftTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 偽 git repo（= SSOT 相当）
        self.repo = self.root / "repo"
        self.repo.mkdir()
        make_git_repo(self.repo)
        # ライブ側 CLAUDE_DIR
        self.claude_dir = self.root / "live"
        self.claude_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()


class TestPrePushCommandsDrift(PrePushDriftTestCase):
    """distribute.py を使ったドリフト検出テスト"""

    def test_drift_detected_when_file_differs(self):
        """harness の distribute 対象ファイルとライブ側が異なる → stderr にドリフト警告、exit 0"""
        make_core_file(self.repo, "CLAUDE.md", "# ssot content\n")
        setup_pre_push_repo(self.repo)
        # ライブ側に内容の異なる CLAUDE.md を配置
        (self.claude_dir / "CLAUDE.md").write_text("# live modified\n", encoding="utf-8")

        result = run_pre_push(self.repo, self.claude_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("ドリフト", result.stderr)

    def test_no_drift_when_all_match(self):
        """すべて一致 → ドリフト警告なし、exit 0"""
        content = "# ssot content\n"
        make_core_file(self.repo, "CLAUDE.md", content)
        setup_pre_push_repo(self.repo)
        # ライブ側も同一内容
        (self.claude_dir / "CLAUDE.md").write_text(content, encoding="utf-8")

        result = run_pre_push(self.repo, self.claude_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("ドリフト", result.stderr)

    def test_live_only_file_not_reported(self):
        """ライブ側にのみ存在するファイル（SSOT に無い）→ ドリフト警告に含まれない"""
        content = "# ssot content\n"
        make_core_file(self.repo, "CLAUDE.md", content)
        setup_pre_push_repo(self.repo)
        (self.claude_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
        # ライブ側にのみ存在するファイル
        (self.claude_dir / "local-only.md").write_text("local only\n", encoding="utf-8")

        result = run_pre_push(self.repo, self.claude_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("local-only.md", result.stderr)

    def test_no_warning_when_claude_dir_missing(self):
        """CLAUDE_DIR が存在しない → 警告なし exit 0"""
        missing_dir = self.root / "nonexistent"

        env = dict(os.environ)
        env["CLAUDE_DIR"] = str(missing_dir)
        result = subprocess.run(
            ["bash", str(PRE_PUSH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("ドリフト", result.stderr)


class TestPrePushUnmanagedSkillsGuard(PrePushDriftTestCase):
    """未管理スキルの警告: 管理下 = core + extras + rulesync.lock、対象 = Claude と ~/.agents。

    判定は harness_lib/unmanaged_skills.py（harness-doctor.sh と共有）。pre-push は
    push を止めず警告だけ出す: ローカル環境の skill 状態は push する PR と無関係で、
    block すると無関係な commit の push が止まり再承認ループになった（2026-08-29）。
    block 相当の判定は test_harness_doctor.py / test_unmanaged_skills.py が持つ。
    """

    def setUp(self):
        super().setUp()
        # pre-push は repo 内の scripts/harness_lib/unmanaged_skills.py を呼ぶ
        shutil.copytree(
            str(REPO_ROOT / "scripts" / "harness_lib"),
            str(self.repo / "scripts" / "harness_lib"),
        )
        (self.repo / "packages" / "core" / "skills" / "core-skill").mkdir(parents=True)
        # extras submodule 初期化済み（skills/ が存在）を既定の fixture にする
        self.extras_skills = self.repo / "packages" / "extras" / "_active" / "skills"
        (self.extras_skills / "extras-skill").mkdir(parents=True)
        (self.claude_dir / "skills").mkdir()
        self.agents_dir = self.root / "agents-skills"
        self.agents_dir.mkdir()

    def write_allowlist(self, *names: str) -> None:
        (self.repo / "packages" / "core" / "unmanaged-skills-allowlist.json").write_text(
            json.dumps({"$comment": "test", **{n: "reason" for n in names}}),
            encoding="utf-8",
        )

    def write_lock(self, *names: str) -> None:
        (self.repo / "rulesync.lock").write_text(
            json.dumps({
                "lockfileVersion": 1,
                "sources": {"owner/repo": {"skills": {n: {"integrity": "sha256-x"} for n in names}}},
            }),
            encoding="utf-8",
        )

    def run_guard(self, **env_overrides: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CLAUDE_DIR"] = str(self.claude_dir)
        env["AGENTS_SKILLS_DIR"] = str(self.agents_dir)
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(PRE_PUSH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
        )

    def test_curated_skill_declared_in_lock_is_managed(self):
        self.write_lock("curated-skill")
        (self.claude_dir / "skills" / "curated-skill").mkdir()
        (self.claude_dir / "skills" / "core-skill").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("未管理スキル", result.stderr)

    def test_undeclared_skill_in_claude_dir_warns_without_blocking(self):
        self.write_lock("curated-skill")
        (self.claude_dir / "skills" / "rogue-skill").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("未管理スキル 1 件", result.stderr)
        self.assertIn("rogue-skill", result.stderr)
        self.assertIn("harness-doctor.sh", result.stderr)
        self.assertIn("rulesync.jsonc", result.stderr)

    def test_undeclared_skill_in_agents_dir_warns_without_blocking(self):
        self.write_lock("curated-skill")
        (self.agents_dir / "npx-installed").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("npx-installed", result.stderr)

    def test_extras_skill_is_managed(self):
        self.write_lock()
        (self.agents_dir / "extras-skill").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("未管理", result.stderr)

    def test_allowlisted_skill_is_managed(self):
        """installer で入るアプリ（agmsg 等）は allowlist に理由付きで宣言すれば通る。"""
        self.write_lock()
        self.write_allowlist("installer-app")
        (self.agents_dir / "installer-app").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("未管理", result.stderr)

    def test_uninitialized_extras_submodule_is_reported_as_undecidable(self):
        """core-only の checkout では extras 由来か判定できないため、文言を分ける。"""
        self.write_lock()
        shutil.rmtree(self.repo / "packages" / "extras")
        (self.agents_dir / "maybe-extras").mkdir()

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("extras submodule 未初期化", result.stderr)
        self.assertIn("maybe-extras", result.stderr)


class TestPrePushPythonResolution(PrePushDriftTestCase):
    """pre-push の Python 解決は mise.toml に委ねる（バージョンをハードコードしない）。

    以前は `mise exec python@3.12 -- python3` のハードコードで、mise.toml が 3.14 へ
    上がった際に hook だけ置き去りになり、依存（PyYAML）が片方の interpreter にしか
    入らず push gate が落ち続けた（2026-08-05）。mise を PATH 上で stub し、
    `mise which python3` が repo root（mise.toml の解決点）で実体を返すことを
    cwd付きで固定する。
    """

    def test_hook_delegates_python_resolution_to_mise_toml(self):
        content = "# ssot content\n"
        make_core_file(self.repo, "CLAUDE.md", content)
        setup_pre_push_repo(self.repo)
        (self.claude_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
        # stub は読まないが、解決点（repo root の pin）の実体を置いておく
        (self.repo / "mise.toml").write_text('[tools]\npython = "3.14"\n', encoding="utf-8")

        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        log = self.root / "mise-invocations.log"
        stub = bin_dir / "mise"
        stub.write_text(
            "#!/bin/sh\n"
            f'printf \'%s\\n\' "cwd=$(pwd -P)" "$@" >> "{log}"\n'
            "if [ \"${1:-}\" = \"which\" ]; then\n"
            f'  printf \'%s\\n\' "{sys.executable}"\n'
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)

        env = dict(os.environ)
        env["CLAUDE_DIR"] = str(self.claude_dir)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        result = subprocess.run(
            ["bash", str(PRE_PUSH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(log.exists(), msg="hook が PATH 上の mise を経由していない")
        lines = log.read_text(encoding="utf-8").splitlines()
        # repo root を cwd に mise が呼ばれる = mise.toml の pin が解決される
        self.assertEqual(lines[0], f"cwd={self.repo.resolve()}")
        # バージョンのハードコード（exec python@X.Y -- ...）が復活していない
        self.assertEqual(lines[1:3], ["which", "python3"])


class TestPrePushGitEnvSanitized(PrePushDriftTestCase):
    """git は hook 実行時に GIT_DIR 等を export する。pre-push がこれを unset せずに
    unittest を走らせると、テスト内の git subprocess（git init --bare / git config）が
    temp repo ではなく GIT_DIR の指す実 repo に作用する
    （2026-07-12 に実リポジトリの .git/config が core.bare=true 等で汚染された実害）。
    """

    def test_unittest_gate_runs_without_inherited_git_env(self):
        content = "# ssot content\n"
        make_core_file(self.repo, "CLAUDE.md", content)
        setup_pre_push_repo(self.repo)
        (self.claude_dir / "CLAUDE.md").write_text(content, encoding="utf-8")

        # フィクスチャ repo に「GIT_DIR 系 env が見えたら fail する」テストを植える
        (self.repo / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        tests_dir = self.repo / "scripts" / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / "test_env_guard.py").write_text(
            "import os\n"
            "import unittest\n"
            "\n"
            "\n"
            "class TestEnvGuard(unittest.TestCase):\n"
            "    def test_git_discovery_env_is_absent(self):\n"
            "        for var in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):\n"
            "            self.assertNotIn(var, os.environ)\n",
            encoding="utf-8",
        )
        # pre-push は scripts/run-tests.py 経由で unittest を回すので fixture にも実物を置く
        shutil.copy(REPO_ROOT / "scripts" / "run-tests.py", self.repo / "scripts" / "run-tests.py")
        # validate-harness.py は fixture に無いため unittest ゲートのみが走る前提を明示
        validate = self.repo / "scripts" / "validate-harness.py"
        if not validate.exists():
            validate.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

        env = dict(os.environ)
        env["CLAUDE_DIR"] = str(self.claude_dir)
        # git が hook 実行時に export する env を再現
        env["GIT_DIR"] = str(self.repo / ".git")
        result = subprocess.run(
            ["bash", str(PRE_PUSH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(self.repo),
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# bootstrap.sh 上書きサマリーテスト
# ---------------------------------------------------------------------------

def make_fake_repo(path: Path) -> Path:
    """テスト用の最小偽 repo を作成し、bootstrap.sh（新しい殻）をコピーして返す。

    新しい bootstrap.sh は distribute.py を exec するため、
    scripts/ 一式（distribute.py, harness_lib/）もコピーする。
    また packages/targets/claude/config.json も必要。
    """
    core_dir = path / "packages" / "core"
    core_dir.mkdir(parents=True)
    (path / "packages" / "extras").mkdir(parents=True)

    # bootstrap.sh をコピー
    scripts_dir = path / "scripts"
    scripts_dir.mkdir()
    dst_bootstrap = scripts_dir / "bootstrap.sh"
    shutil.copy(str(BOOTSTRAP), str(dst_bootstrap))

    # distribute.py + harness_lib/ をコピー
    copy_scripts_to_repo(path)

    # packages/targets/claude/config.json を設置（bootstrap が distribute を呼ぶ）
    claude_target_dir = path / "packages" / "targets" / "claude"
    claude_target_dir.mkdir(parents=True, exist_ok=True)

    return dst_bootstrap


def _write_claude_config(fake_repo: Path, claude_dir: Path,
                          extra_distribute: dict | None = None) -> None:
    """bootstrap テスト用の packages/targets/claude/config.json を書く。

    extra_distribute: CLAUDE.md 以外の配布エントリを追加したい場合に使う。
    """
    distribute = {
        "CLAUDE.md": {"source": "packages/core/CLAUDE.md"},
    }
    if extra_distribute:
        distribute.update(extra_distribute)

    claude_target_dir = fake_repo / "packages" / "targets" / "claude"
    claude_target_dir.mkdir(parents=True, exist_ok=True)
    (claude_target_dir / "config.json").write_text(
        json.dumps({
            "name": "claude",
            "displayName": "Claude Code",
            "configDir": "~/.claude",
            "configFile": "settings.json",
            "instructionsFile": "CLAUDE.md",
            "distribute": distribute,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def run_bootstrap(bootstrap_sh: Path, claude_dir: Path, dry_run: bool = False) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_DIR"] = str(claude_dir)
    # bootstrap.sh must use the same supported interpreter as this test suite;
    # PATH may still resolve the macOS system Python 3.9 in subprocesses.
    env["PYTHON_BIN"] = sys.executable
    # fake_repo は claude target しか持たないので明示指定する。
    # 全 target デフォルトのまま走らせると codex/opencode の config.json 不在で落ちる
    cmd = ["bash", str(bootstrap_sh), "--targets", "claude", "--skip-submodule"]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=60,
    )


class BootstrapOverwriteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fake_repo = self.root / "fake_repo"
        self.fake_repo.mkdir()
        self.bootstrap_sh = make_fake_repo(self.fake_repo)
        self.claude_dir = self.root / "live"
        self.claude_dir.mkdir()
        # config.json を設置
        _write_claude_config(self.fake_repo, self.claude_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def add_core_file(self, rel: str, content: str) -> None:
        """packages/core/<rel> に SSOT ファイルを作成する。"""
        target = self.fake_repo / "packages" / "core" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def add_live_file(self, rel: str, content: str) -> None:
        """$CLAUDE_DIR/<rel> にライブ側ファイルを作成する。"""
        target = self.claude_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class TestBootstrapOverwriteSummary(BootstrapOverwriteTestCase):
    def test_overwrite_warning_when_live_differs(self):
        """ライブ側に内容の異なる既存ファイルがある → stdout に上書き警告 + backup に退避"""
        self.add_core_file("CLAUDE.md", "# SSOT\n")
        self.add_live_file("CLAUDE.md", "# Live modified\n")

        result = run_bootstrap(self.bootstrap_sh, self.claude_dir)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("上書き", combined)
        self.assertIn("SSOT-first 原則", combined)

        # backup ディレクトリにファイルが退避されているか確認
        backups_dir = self.claude_dir / "backups"
        self.assertTrue(backups_dir.exists(), "backups/ ディレクトリが存在しない")
        backed_up = list(backups_dir.rglob("CLAUDE.md"))
        self.assertTrue(len(backed_up) > 0, "CLAUDE.md が backup されていない")

    def test_no_warning_when_all_same(self):
        """全ファイル同一 → 警告なし"""
        self.add_core_file("CLAUDE.md", "# SSOT\n")
        self.add_live_file("CLAUDE.md", "# SSOT\n")

        result = run_bootstrap(self.bootstrap_sh, self.claude_dir)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertNotIn("上書き", combined)


if __name__ == "__main__":
    unittest.main()

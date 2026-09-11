#!/usr/bin/env python3
"""block-edit-on-main.sh hook のフィクスチャテスト。

main/master ブランチ上での Edit/Write を直接ブロックするガードレールの中核 hook。
一時 git repo + 隔離した HOME（実マシンの ~/.config/gwm/config.toml を拾わない）
で fixture を組み、exit code を検証する。
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-edit-on-main.sh"


def _make_git_repo(parent: Path, name: str = "myrepo", branch: str = "main") -> Path:
    repo = parent / name
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


def _run(
    file_path: str,
    tool_name: str = "Edit",
    cwd: str = None,
    home: str = None,
    disable_tmp_bypass: bool = True,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = home
    # 既定ではテスト fixture が TMPDIR（/tmp 配下）に作られても hook がバイパス
    # しないよう /tmp バイパスを無効化する。/tmp バイパス自体を検証するテストは
    # disable_tmp_bypass=False で従来挙動（バイパス有効）を確認する。
    if disable_tmp_bypass:
        env["CLAUDE_HOOK_ALLOW_TMP_PATHS"] = "1"
    else:
        env.pop("CLAUDE_HOOK_ALLOW_TMP_PATHS", None)
    env["TOOL_INPUT"] = json.dumps(
        {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
    )
    return subprocess.run(
        ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, cwd=cwd, env=env
    )


def _run_patch(
    patch_input: str = None,
    tool_name: str = "Write",
    cwd: str = None,
    home: str = None,
    disable_tmp_bypass: bool = True,
) -> subprocess.CompletedProcess:
    """apply_patch（bridge が Write として届ける）を模した file_path 空の呼び出し。

    HOOK_CWD は JSON の `.cwd` を持たないため、hook 内の `${HOOK_CWD:=$PWD}` フォール
    バックにより subprocess の実 cwd（引数の cwd）で解決される。
    """
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = home
    if disable_tmp_bypass:
        env["CLAUDE_HOOK_ALLOW_TMP_PATHS"] = "1"
    else:
        env.pop("CLAUDE_HOOK_ALLOW_TMP_PATHS", None)
    tool_input = {"file_path": ""}
    if patch_input is not None:
        tool_input["input"] = patch_input
    env["TOOL_INPUT"] = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run(
        ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, cwd=cwd, env=env
    )


class TestBlockEditOnMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 実マシンの ~/.config/gwm/config.toml を拾わないよう HOME を隔離する
        self.fake_home = self.root / "home"
        self.fake_home.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_edit_on_main_branch_is_blocked(self):
        repo = _make_git_repo(self.root, branch="main")
        file_path = str(repo / "file.txt")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_edit_on_master_branch_is_blocked(self):
        repo = _make_git_repo(self.root, branch="master")
        file_path = str(repo / "file.txt")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_edit_on_feature_branch_is_allowed(self):
        repo = _make_git_repo(self.root, branch="feature-x")
        file_path = str(repo / "file.txt")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_edit_under_gwm_worktree_base_is_allowed(self):
        # gwm の worktree_base_path 配下は、main ブランチ上でも許可される。
        gwm_base = self.root / "worktrees"
        gwm_base.mkdir()
        gwm_config_dir = self.fake_home / ".config" / "gwm"
        gwm_config_dir.mkdir(parents=True)
        (gwm_config_dir / "config.toml").write_text(
            f'worktree_base_path = "{gwm_base}"\n'
        )
        repo = _make_git_repo(gwm_base, name="worktree-repo", branch="main")
        file_path = str(repo / "file.txt")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_edit_outside_git_repo_is_allowed(self):
        outside_dir = self.root / "not-a-repo"
        outside_dir.mkdir()
        file_path = str(outside_dir / "file.txt")
        result = _run(file_path, cwd=str(outside_dir), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_non_edit_write_tool_is_allowed(self):
        repo = _make_git_repo(self.root, branch="main")
        file_path = str(repo / "file.txt")
        result = _run(file_path, tool_name="Bash", cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_tmp_file_path_is_allowed_even_on_main(self):
        repo = _make_git_repo(self.root, branch="main")
        # /tmp/ 配下は git リポジトリ判定に関わらず常に許可される（バイパス有効の既定挙動）
        result = _run(
            "/tmp/scratch-file.txt",
            cwd=str(repo),
            home=str(self.fake_home),
            disable_tmp_bypass=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_harunon_harness_repo_is_exempted_even_on_main(self):
        # harness リポジトリ自体は main で直接作業する運用のため常に許可される
        repo = _make_git_repo(self.root, name="harunon-harness", branch="main")
        file_path = str(repo / "file.txt")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_apply_patch_envelope_relative_path_on_main_is_blocked(self):
        # pi の apply_patch は file_path を持たず、tool_input.input に Codex patch
        # envelope が入る。相対パスは呼び出し元 cwd 基準で main ブランチ判定する。
        repo = _make_git_repo(self.root, branch="main")
        (repo / "existing.txt").write_text("old\n")
        patch = (
            "*** Begin Patch\n"
            "*** Update File: existing.txt\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "*** End Patch"
        )
        result = _run_patch(patch, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_apply_patch_envelope_relative_path_on_feature_branch_is_allowed(self):
        repo = _make_git_repo(self.root, branch="feature-x")
        (repo / "existing.txt").write_text("old\n")
        patch = (
            "*** Begin Patch\n"
            "*** Update File: existing.txt\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "*** End Patch"
        )
        result = _run_patch(patch, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_apply_patch_envelope_multiple_paths_one_on_main_is_blocked(self):
        # envelope に複数ファイルがあり、1 つでも main 直編集に該当すればブロックする。
        # feature ブランチのパスを先に、main ブランチのパスを後に置き、途中で
        # 判定を打ち切らず全候補を確認することを確認する。
        repo_feature = _make_git_repo(self.root, name="repo-feature", branch="feature-x")
        repo_main = _make_git_repo(self.root, name="repo-main", branch="main")
        feature_file = repo_feature / "a.txt"
        main_file = repo_main / "b.txt"
        feature_file.write_text("1\n")
        main_file.write_text("1\n")
        patch = (
            "*** Begin Patch\n"
            f"*** Update File: {feature_file}\n"
            "@@\n"
            "-1\n"
            "+2\n"
            f"*** Update File: {main_file}\n"
            "@@\n"
            "-1\n"
            "+2\n"
            "*** End Patch"
        )
        result = _run_patch(patch, cwd=str(self.root), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_apply_patch_without_envelope_falls_back_to_cwd_guard_on_main(self):
        # file_path も envelope パスも取れない場合、素通りせず cwd 自体をガード対象にする
        # （fail-closed。2026-08-14 の apply_patch すり抜けインシデントの対応）。
        repo = _make_git_repo(self.root, branch="main")
        result = _run_patch(None, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_apply_patch_without_envelope_falls_back_to_cwd_guard_on_feature_branch(self):
        repo = _make_git_repo(self.root, branch="feature-x")
        result = _run_patch(None, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)

    def test_apply_patch_without_envelope_under_tmp_cwd_is_allowed(self):
        # cwd フォールバック先が /tmp 配下なら、他の候補パスと同様 /tmp バイパスが効く
        # （バイパス有効の既定挙動）。
        result = _run_patch(
            None, cwd="/tmp", home=str(self.fake_home), disable_tmp_bypass=False
        )
        self.assertEqual(result.returncode, 0)

    def test_dotdot_traversal_out_of_tmp_bypass_on_main_is_blocked(self):
        # 「/tmp から始まる」ように見えても、`..` を canonicalize すれば実際には
        # main リポジトリを指す traversal。字面判定だけだと tmp バイパスに誤って
        # 乗ってしまう（2026-08-14 Codex review P1-2）。
        #
        # tmp バイパスを有効にしたまま検証する必要があるため、fixture repo は
        # /tmp 系の外に置かなければならない（TemporaryDirectory は /private/tmp
        # 配下になるので使えない）。書き込み可否は環境依存（CI runner は workspace
        # 書き込み可 / ローカル sandbox は nested .git への書き込みを拒否）なので、
        # 候補場所を順に試し、どこにも作れなければ skip する。CI では常に実行される。
        # canonicalize-before-bypass 自体の regression は同一コードパスを通る
        # test_dotdot_traversal_through_claude_dir_on_main_is_blocked が全環境で守る。
        candidates = [
            Path(__file__).resolve().parent,
            Path.home() / ".local" / "bin",
        ]
        outside_tmp_root = None
        repo = None
        for base in candidates:
            root = None
            try:
                base.mkdir(parents=True, exist_ok=True)
                root = Path(tempfile.mkdtemp(dir=str(base), prefix="dotdot-test-"))
                candidate_repo = _make_git_repo(root, branch="main")
            except (OSError, subprocess.CalledProcessError):
                if root is not None:
                    shutil.rmtree(root, ignore_errors=True)
                continue
            real = os.path.realpath(str(candidate_repo))
            if real.startswith("/tmp/") or real.startswith("/private/tmp/"):
                shutil.rmtree(root, ignore_errors=True)
                continue
            outside_tmp_root = root
            repo = candidate_repo
            break
        if outside_tmp_root is None:
            self.skipTest(
                "/tmp 外に fixture repo を作れる書き込み可能な場所がない（sandbox 環境）。"
                "CI では実行される"
            )
        try:
            real_repo = os.path.realpath(str(repo))
            traversal = "/tmp/" + "../" * 20 + real_repo.lstrip("/") + "/file.txt"
            result = _run(
                traversal, cwd=str(repo), home=str(self.fake_home), disable_tmp_bypass=False
            )
            self.assertEqual(result.returncode, 2)
        finally:
            shutil.rmtree(outside_tmp_root, ignore_errors=True)

    def test_dotdot_traversal_through_claude_dir_on_main_is_blocked(self):
        # `<repo>/.claude/../tracked.txt` は字面には `/.claude/` を含むが、
        # canonicalize すれば `.claude` を経由しないただの repo 直下ファイル。
        repo = _make_git_repo(self.root, branch="main")
        claude_dir = repo / ".claude"
        claude_dir.mkdir()
        tracked = repo / "tracked.txt"
        tracked.write_text("x\n")
        file_path = str(claude_dir) + "/../tracked.txt"
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 2)

    def test_edit_under_claude_dir_is_allowed_even_on_main(self):
        # 正規の（traversal を含まない）.claude/ 配下バイパスは引き続き効く。
        repo = _make_git_repo(self.root, branch="main")
        claude_dir = repo / ".claude"
        claude_dir.mkdir()
        file_path = str(claude_dir / "settings.json")
        result = _run(file_path, cwd=str(repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

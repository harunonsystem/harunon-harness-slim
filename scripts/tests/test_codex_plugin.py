#!/usr/bin/env python3
"""Codex plugin adapter contract tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages/runtimes/codex/harunon-core"
ADAPTER = PLUGIN_ROOT / "scripts/codex_hook.py"
BUILDER = REPO_ROOT / "scripts/build-codex-plugin.py"

# dispatcher は同梱された policy/hook-pipeline.json から配線を導出する。SSOT の skeleton には
# policy/ が無く、ビルド時に materialize されるため、テストはビルド済み成果物から読み込む
# （skeleton へ fallback パスを足すと、本番での配布漏れを黙って隠すことになる）。
_BUILT = tempfile.TemporaryDirectory()
subprocess.run(
    [sys.executable, str(BUILDER), "--output", str(Path(_BUILT.name) / "out")],
    check=True, capture_output=True, text=True,
)
BUILT_PLUGIN = Path(_BUILT.name) / "out/plugins/harunon-core"


def wired_hooks(adapter, event: dict) -> list[str]:
    """event の tool に配線された hook のファイル名を order 順で返す。"""
    return [hook["file"] for hook in adapter.candidate_hooks(event)]


def load_adapter(source: Path = None):
    target = source or (BUILT_PLUGIN / "scripts/codex_hook.py")
    spec = importlib.util.spec_from_file_location("codex_hook", target)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Codex adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCodexPlugin(unittest.TestCase):
    def test_manifest_and_single_hook_dispatcher_exist(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        hooks = json.loads(
            (PLUGIN_ROOT / "hooks/hooks.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["name"], "harunon-core")
        pre_tool = hooks["hooks"]["PreToolUse"]
        self.assertEqual(len(pre_tool), 1)
        self.assertEqual(
            pre_tool[0]["matcher"],
            "^(Bash|EnterWorktree|Write|Edit|write_file|edit_file|apply_patch|mcp__.*github.*)$",
        )
        self.assertIn("codex_hook.py", pre_tool[0]["hooks"][0]["command"])

    def test_codex_does_not_add_review_gate_to_github_operations(self) -> None:
        adapter = load_adapter()

        for event in (
            {"tool_name": "Bash", "tool_input": {"command": "gh pr create --fill"}},
            {"tool_name": "mcp__github__create_pull_request", "tool_input": {}},
            {"tool_name": "mcp__github__merge_pull_request", "tool_input": {}},
        ):
            self.assertNotIn("block-pr-without-codex-review.sh", wired_hooks(adapter, event))

    def test_codex_delegates_push_approval_while_wiring_block_dangerous_in_bash(self) -> None:
        """push 承認は Codex native permissions / guardian_approval が所有する。

        2026-08 以前は block-dangerous-in-bash.sh 自体を codex に配線していなかった
        （dispatcher が選ばない）ことでこれを保証していた。同 hook を codex にも
        配線した後は、rule 単位（danger-rules.json の git-push.absent.codex）で
        同じ委譲を保証する。この委譲が保たれていることは (a) verify-before-push.sh
        が依然 codex に選ばれないこと、(b) block-dangerous-in-bash.sh は選ばれるが
        push コマンドを deny しないこと、の両方で確認する。
        """
        adapter = load_adapter()

        scripts = wired_hooks(
            adapter,
            {"tool_name": "Bash", "tool_input": {"command": "git push -u origin feature"}},
        )
        self.assertIn("block-dangerous-in-bash.sh", scripts)
        self.assertNotIn("verify-before-push.sh", scripts)

        hook = BUILT_PLUGIN / "hooks" / "block-dangerous-in-bash.sh"
        env = {**os.environ, "HARNESS_RUNTIME": "codex"}

        allowed = subprocess.run(
            ["bash", str(hook)],
            input=json.dumps({"tool_input": {"command": "git push -u origin feature"}}),
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(allowed.returncode, 0, msg=allowed.stderr)

        denied = subprocess.run(
            ["bash", str(hook)],
            input=json.dumps({"tool_input": {"command": "git commit -m x --no-verify"}}),
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(denied.returncode, 2, msg=denied.stdout)

    def test_codex_enforces_worktree_policy_after_git_global_options(self) -> None:
        adapter = load_adapter()

        scripts = wired_hooks(
            adapter,
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git -C /repo worktree add ../wt feature"
                },
            },
        )

        self.assertIn("enforce-gwm-for-worktree.sh", scripts)

    def test_command_repo_ignores_cd_in_command(self) -> None:
        adapter = load_adapter()

        with tempfile.TemporaryDirectory() as workdir, tempfile.TemporaryDirectory() as other:
            repo = adapter.session_cwd(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "workdir": workdir,
                        "command": f"cd {other} && grep foo bar",
                    },
                }
            )

        self.assertEqual(repo, Path(workdir).resolve())

    def test_command_repo_uses_workdir_as_relative_base(self) -> None:
        adapter = load_adapter()

        with tempfile.TemporaryDirectory() as workdir:
            # 相対 cd（"sub"）は base cwd を破棄して解決してはいけない（P1-A の再発防止）。
            repo = adapter.session_cwd(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "workdir": workdir,
                        "command": "cd sub && grep foo bar",
                    },
                }
            )

        self.assertEqual(repo, Path(workdir).resolve())

    def test_codex_hook_denies_when_base_cwd_is_missing(self) -> None:
        event = {
            "tool_name": "Bash",
            "tool_input": {
                "workdir": "/nonexistent-base-zzz-codex-hook-test",
                "command": "echo hi",
            },
        }
        result = subprocess.run(
            [sys.executable, str(BUILT_PLUGIN / "scripts/codex_hook.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_codex_denial_keeps_actionable_stderr_with_stdout(self) -> None:
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as directory:
            hook = Path(directory) / "fixture.sh"
            hook.write_text(
                '#!/usr/bin/env bash\n'
                'printf "generic denial"\n'
                'printf "next action: approve-push.sh" >&2\n'
                "exit 2\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            event = {"tool_name": "Bash", "tool_input": {"command": "git push"}}
            with mock.patch.object(adapter, "HOOKS", Path(directory)), mock.patch.object(
                adapter,
                "candidate_hooks",
                return_value=({"file": hook.name, "required": True, "when": {}},),
            ):
                code, reason = adapter.run_shell_pipeline(event, Path(directory))

        self.assertEqual(code, 2)
        self.assertEqual(reason, "generic denial\nnext action: approve-push.sh")

    def test_command_condition_gates_the_hook_inside_the_pipeline(self) -> None:
        """when.commandEre は pipeline 内で評価する（配線 = 実行ではない）。"""
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as directory:
            hook = Path(directory) / "fixture.sh"
            hook.write_text(
                '#!/usr/bin/env bash\ncat > /dev/null\necho "matched" >&2\nexit 2\n',
                encoding="utf-8",
            )
            hook.chmod(0o755)
            wiring = ({"file": hook.name, "required": True, "when": {"commandEre": r"\bcommit\b"}},)
            with mock.patch.object(adapter, "HOOKS", Path(directory)), mock.patch.object(
                adapter, "candidate_hooks", return_value=wiring
            ):
                run = lambda command: adapter.run_shell_pipeline(  # noqa: E731
                    {"tool_name": "Bash", "tool_input": {"command": command}}, Path(directory)
                )
                self.assertEqual(run("git commit -m x")[0], 2)
                self.assertEqual(run("git status"), (0, ""))


class TestBlockEditOnMain(unittest.TestCase):
    """Codex の編集ツールが main 直編集ガードに届くこと（2026-08-31 の配線）。"""

    def _guard_env(self) -> dict[str, str]:
        # fixture repo は TMPDIR 配下なので、hook の /tmp バイパスを無効化しないと
        # Linux CI（TMPDIR=/tmp）では素通りしてテストが常に緑になる。
        # rigor profile は casual だとガード自体が無効なので実在しないパスへ倒す。
        return {
            **os.environ,
            "CLAUDE_HOOK_ALLOW_TMP_PATHS": "1",
            "RIGOR_PATTERNS_FILE": "/nonexistent-rigor-patterns.json",
            "RIGOR_LOCAL_FILE": "/nonexistent-rigor-local.json",
        }

    def _make_repo(self, parent: str, branch: str) -> Path:
        # harness 自身は main 直運用なので hook が素通しする。別名で作る
        repo = Path(parent) / "demo-repo"
        repo.mkdir()
        run = lambda *args: subprocess.run(  # noqa: E731
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
        run("init", "-b", "main")
        run("config", "user.email", "test@example.com")
        run("config", "user.name", "Test")
        (repo / "notes.md").write_text("seed\n", encoding="utf-8")
        run("add", "notes.md")
        run("commit", "-m", "seed")
        if branch != "main":
            run("switch", "-c", branch)
        return repo

    def _dispatch(self, event: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BUILT_PLUGIN / "scripts/codex_hook.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
            env=self._guard_env(),
        )

    def test_edit_tools_select_the_main_branch_guard(self) -> None:
        adapter = load_adapter()

        for tool in ("apply_patch", "write_file", "edit_file", "Write", "Edit"):
            self.assertIn(
                "block-edit-on-main.sh",
                wired_hooks(adapter, {"tool_name": tool, "tool_input": {}}),
                msg=tool,
            )

        self.assertNotIn(
            "block-edit-on-main.sh",
            wired_hooks(
                adapter, {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
            ),
        )

    def test_apply_patch_on_main_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            repo = self._make_repo(parent, "main")
            result = self._dispatch(
                {
                    "tool_name": "apply_patch",
                    "cwd": str(repo),
                    "tool_input": {"input": "*** Update File: notes.md\n"},
                }
            )

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("main-branch guard", payload["hookSpecificOutput"]["permissionDecisionReason"])

    def test_apply_patch_on_a_feature_branch_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            repo = self._make_repo(parent, "feature/x")
            result = self._dispatch(
                {
                    "tool_name": "apply_patch",
                    "cwd": str(repo),
                    "tool_input": {"input": "*** Update File: notes.md\n"},
                }
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class TestPostEditChecks(unittest.TestCase):
    """PostToolUse: write/edit 後の品質チェックを additionalContext で返し、deny しない。"""

    def test_hooks_json_wires_post_tool_use_for_edit_tools(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
        post = hooks["hooks"]["PostToolUse"]
        self.assertEqual(len(post), 1)
        for tool in ("Write", "Edit", "apply_patch"):
            self.assertRegex(tool, post[0]["matcher"])
        self.assertNotRegex("Bash", post[0]["matcher"])
        self.assertIn("codex_hook.py", post[0]["hooks"][0]["command"])

    def test_builder_bundles_post_edit_assets_outside_pipeline_hooks(self) -> None:
        self.assertTrue((BUILT_PLUGIN / "hooks/post-edit/post-edit-checks.sh").is_file())
        self.assertTrue((BUILT_PLUGIN / "hooks/post-edit/fix_gfm_tables.py").is_file())

    def test_edited_paths_from_direct_and_apply_patch_inputs(self) -> None:
        adapter = load_adapter()
        self.assertEqual(
            adapter.edited_paths({"tool_input": {"file_path": "/a/b.sh"}}), ["/a/b.sh"]
        )
        patch = (
            "*** Begin Patch\n*** Update File: scripts/x.sh\n@@\n-a\n+b\n"
            "*** Add File: docs/new.md\n+hi\n*** End Patch\n"
        )
        self.assertEqual(
            adapter.edited_paths({"tool_input": {"patch": patch}}),
            ["scripts/x.sh", "docs/new.md"],
        )

    def test_broken_json_is_reported_as_additional_context(self) -> None:
        if not any(
            os.access(os.path.join(d, "jq"), os.X_OK) for d in os.environ["PATH"].split(os.pathsep)
        ):
            self.skipTest("jq がない")
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{broken", encoding="utf-8")
            event = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": tmp,
                "tool_input": {"file_path": "bad.json"},
            }
            result = subprocess.run(
                [sys.executable, str(BUILT_PLUGIN / "scripts/codex_hook.py")],
                input=json.dumps(event), capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertIn("invalid JSON", out["additionalContext"])
        self.assertNotIn("permissionDecision", out)

    def test_clean_file_and_non_edit_tool_print_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text("{}", encoding="utf-8")
            for event in (
                {"hook_event_name": "PostToolUse", "tool_name": "Write", "cwd": tmp,
                 "tool_input": {"file_path": str(good)}},
                {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": tmp,
                 "tool_input": {"command": "ls"}},
            ):
                result = subprocess.run(
                    [sys.executable, str(BUILT_PLUGIN / "scripts/codex_hook.py")],
                    input=json.dumps(event), capture_output=True, text=True, check=False,
                )
                self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

if __name__ == "__main__":
    unittest.main()

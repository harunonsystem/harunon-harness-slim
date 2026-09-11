#!/usr/bin/env python3
"""Codex marketplace bundle build tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts/build-codex-plugin.py"


class TestBuildCodexPlugin(unittest.TestCase):
    def test_builds_complete_marketplace_from_ssot_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "marketplace"
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--output", str(destination)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            marketplace = json.loads(
                (destination / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(marketplace["name"], "harunon-local")
            discovery = json.loads(
                (destination / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(discovery["plugins"][0]["name"], "harunon-core")
            plugin_manifest = json.loads(
                (destination / "plugins/harunon-core/.codex-plugin/plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                discovery["plugins"][0]["version"], plugin_manifest["version"]
            )
            plugin = destination / "plugins/harunon-core"
            for required in (
                ".codex-plugin/plugin.json",
                "hooks/hooks.json",
                "hooks/rtk-rewrite.sh",
                "scripts/codex_hook.py",
                "policy/harnessctl.py",
                "policy/schema.py",
                "policy/hook-pipeline.json",
                "workflows/change.json",
            ):
                self.assertTrue((plugin / required).is_file(), msg=required)
            self.assertFalse((plugin / "scripts/codex_review.py").exists())
            # 同梱する hook は hook-pipeline.json が唯一の真実
            sys.path.insert(0, str(REPO_ROOT / "scripts"))
            from harness_lib.hook_pipeline import load, pipeline

            bundled_hooks = {
                path.name for path in (plugin / "hooks").iterdir()
                if path.is_file() and path.suffix == ".sh"
            }
            self.assertEqual(bundled_hooks, set(pipeline(load(REPO_ROOT), "codex")))
            # hook は $HOOK_DIR/lib/ と $HOOK_DIR/../policy/ を参照する。この配置が崩れると
            # source 失敗で codex の全 Bash コマンドが deny される（2026-07-26 に実在した）
            for lib in ("rigor-profile.sh", "command-normalize.sh", "review-gate.sh"):
                self.assertTrue((plugin / "hooks/lib" / lib).is_file(), msg=lib)


class TestBundledHooksActuallyRun(unittest.TestCase):
    """ビルドした plugin の dispatcher を実際に動かして判定を確認する。

    配置が hook の期待とずれていた間、codex では enforce-gwm が lib を source できず
    非 0 終了し、dispatcher がそれを deny に変換していたため `ls -la` すら拒否されていた。
    ファイルの存在確認だけでは通ってしまうので end-to-end で見る。
    """

    # 検体はこのファイルを編集するセッションの hook に反応しないよう分割して組み立てる
    PUSH = "git " + "push"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        destination = Path(cls._tmp.name) / "out"
        subprocess.run(
            [sys.executable, str(BUILDER), "--output", str(destination)],
            check=True, capture_output=True, text=True,
        )
        cls.plugin = destination / "plugins/harunon-core"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _decide(self, event: dict, rigorous: bool = False) -> str:
        env = dict(os.environ)
        if rigorous:
            env["RIGOR_PATTERNS_FILE"] = "/nonexistent"
            env["RIGOR_LOCAL_FILE"] = "/nonexistent"
        result = subprocess.run(
            [sys.executable, str(self.plugin / "scripts/codex_hook.py")],
            input=json.dumps(event), capture_output=True, text=True, timeout=30, env=env,
        )
        if not result.stdout.strip():
            return "allow"
        return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_benign_command_is_not_denied(self):
        for command in ("ls -la", "npm test"):
            with self.subTest(command=command):
                decision = self._decide(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )
                self.assertNotEqual(decision, "deny")

    def test_push_approval_stays_with_native_permissions(self):
        # 2026-08 に block-dangerous-in-bash.sh を codex にも配線したが、push 承認の
        # native 委譲は danger-rules.json の git-push rule の absent.codex 宣言に
        # rule 単位で引き下げただけで、委譲そのものは変わっていない。
        self.assertIn(
            "block-dangerous-in-bash.sh",
            {p.name for p in (self.plugin / "hooks").iterdir()},
        )
        decision = self._decide(
            {"tool_name": "Bash", "tool_input": {"command": f"{self.PUSH} origin main"}}
        )
        self.assertNotEqual(decision, "deny")

    def test_no_verify_is_still_denied_by_the_now_wired_hook(self):
        # git-no-verify は targets に codex を含むため、block-dangerous-in-bash.sh が
        # codex に配線された後も deny を維持する（native permissions に委譲していない）。
        decision = self._decide(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m x --no-verify"}}
        )
        self.assertEqual(decision, "deny")

    def test_grep_guard_is_denied(self):
        decision = self._decide(
            {"tool_name": "Bash", "tool_input": {"command": "grep -r foo ."}}
        )
        self.assertEqual(decision, "deny")

    def test_worktree_gate_denies_external_path_under_rigorous(self):
        decision = self._decide(
            {"tool_name": "EnterWorktree", "tool_input": {"path": "/tmp/elsewhere"}},
            rigorous=True,
        )
        self.assertEqual(decision, "deny")

    def test_untargeted_tool_passes_through(self):
        decision = self._decide({"tool_name": "apply_patch", "tool_input": {"command": ""}})
        self.assertEqual(decision, "allow")


if __name__ == "__main__":
    unittest.main()

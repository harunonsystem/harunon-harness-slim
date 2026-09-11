"""新しい開発マシン向け setup-machine.sh の契約テスト。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_MACHINE = REPO_ROOT / "scripts" / "setup-machine.sh"


class SetupMachineTest(unittest.TestCase):
    """外部 CLI と mise を隔離してセットアップの分岐を検証する。"""

    def _prepare_path(
        self,
        root: Path,
        *,
        mise: bool = False,
        pi: bool = False,
        difit: bool = False,
        ocr: bool = False,
    ) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for command in ("dirname", "pwd"):
            command_path = shutil.which(command)
            self.assertIsNotNone(command_path, f"{command} がテスト環境に必要")
            (bin_dir / command).symlink_to(command_path)

        def write_command(name: str, body: str = "exit 0\n") -> None:
            path = bin_dir / name
            path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
            path.chmod(0o755)

        if mise:
            write_command(
                "mise",
                'printf "%s\\n" "$*" >> "$SETUP_MISE_LOG"\n',
            )
        if pi:
            write_command("pi")
        if difit:
            write_command("difit")
        if ocr:
            write_command("ocr")
        return bin_dir

    def _run_setup(
        self,
        *,
        mise: bool = False,
        pi: bool = False,
        difit: bool = False,
        ocr: bool = False,
        input_text: str = "",
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            log_path = temp_root / "mise.log"
            bin_dir = self._prepare_path(temp_root, mise=mise, pi=pi, difit=difit, ocr=ocr)
            env = os.environ.copy()
            env["PATH"] = str(bin_dir)
            env["SETUP_MISE_LOG"] = str(log_path)
            result = subprocess.run(
                ["/bin/bash", str(SETUP_MACHINE)],
                input=input_text,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            mise_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            return result, mise_log

    def test_missing_mise_fails_before_prompts(self) -> None:
        result, _ = self._run_setup()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mise が見つかりません", result.stderr)
        self.assertNotIn("追加しますか", result.stdout)

    def test_existing_clis_are_skipped_without_mise(self) -> None:
        result, mise_log = self._run_setup(mise=True, pi=True, difit=True, ocr=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("✓ Pi:", result.stdout)
        self.assertIn("✓ difit:", result.stdout)
        self.assertNotIn("追加しますか", result.stdout)
        self.assertEqual(mise_log, "")

    def test_rejections_do_not_call_mise(self) -> None:
        result, mise_log = self._run_setup(mise=True, input_text="n\nn\nn\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mise_log, "")
        self.assertEqual(result.stdout.count("スキップしました"), 3)

    def test_end_of_input_defaults_to_rejection(self) -> None:
        result, mise_log = self._run_setup(mise=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mise_log, "")
        self.assertEqual(result.stdout.count("スキップしました"), 3)

    def test_approvals_use_pinned_global_mise_packages(self) -> None:
        result, mise_log = self._run_setup(mise=True, input_text="y\ny\ny\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            mise_log.splitlines(),
            [
                "use --global --pin npm:@earendil-works/pi-coding-agent",
                "use --global --pin npm:difit",
                "use --global --pin npm:@alibaba-group/open-code-review",
            ],
        )

    def test_output_includes_follow_up_guidance(self) -> None:
        result, _ = self._run_setup(mise=True, pi=True, difit=True, ocr=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        for guidance in (
            "mise install",
            "git submodule update --init packages/extras/_active",
            "./scripts/bootstrap.sh",
            "pi を起動して /mcp でOAuth接続を確認",
        ):
            self.assertIn(guidance, result.stdout)


if __name__ == "__main__":
    unittest.main()

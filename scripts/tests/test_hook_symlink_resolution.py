#!/usr/bin/env python3
"""hook が symlink 経由で起動されても隣の lib/ と policy/ を解決できるか検証する。

hook は自身の隣の lib/review-gate.sh などを source する。distribute は実ファイルを
コピーするため通常運転では symlink 経路を通らないが、ADR-001 が「ドリフト起因の
事故が再発した場合は symlink 方式への移行を最優先で検討する」としているため、
symlink 経路が壊れていないことを機械的に固定する。

旧実装は `[ -L "$P" ] && P="$(readlink "$P")"` の単一段で、相対 symlink の場合に
readlink が相対パスを返すため dirname が呼び出し元の cwd 基準になって壊れた。
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORE = REPO_ROOT / "packages" / "core"
HOOKS = CORE / "hooks"

# 解決に失敗すると fail-closed で明示的に落ちるため、観測点として使う
PROBE_HOOK = "block-dangerous-in-bash.sh"


class TestHookSymlinkResolution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        # 配布後のレイアウト（hooks/ と policy/ が兄弟）を再現する
        shutil.copytree(HOOKS, root / "hooks")
        shutil.copytree(CORE / "policy", root / "policy")
        self.root = root

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, script: Path, command: str, cwd: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["HARNESS_RUNTIME"] = "claude"
        env["TOOL_INPUT"] = f'{{"tool_name":"Bash","tool_input":{{"command":"{command}"}}}}'
        return subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=20, cwd=str(cwd), env=env,
        )

    def test_resolves_lib_when_invoked_through_a_relative_symlink(self):
        """相対 symlink 経由でも lib/ と policy/ を見つける（旧実装が壊れていたケース）。"""
        link_dir = self.root / "bin"
        link_dir.mkdir()
        link = link_dir / PROBE_HOOK
        link.symlink_to(Path("..") / "hooks" / PROBE_HOOK)  # 相対ターゲット

        # cwd を symlink とも実体とも無関係な場所にして、cwd 依存の解決を検出する
        result = self._run(link, "git status", cwd=Path(self._tmp.name))

        self.assertNotIn("読めません", result.stderr)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_resolves_lib_when_invoked_through_a_chained_symlink(self):
        """多段 symlink でも解決する。"""
        first = self.root / "bin1"
        second = self.root / "bin2"
        first.mkdir()
        second.mkdir()
        (first / PROBE_HOOK).symlink_to(Path("..") / "hooks" / PROBE_HOOK)
        (second / PROBE_HOOK).symlink_to(first / PROBE_HOOK)

        result = self._run(second / PROBE_HOOK, "git status", cwd=Path(self._tmp.name))

        self.assertNotIn("読めません", result.stderr)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_all_hooks_share_one_resolution_implementation(self):
        """lib/ を source する hook は全て同じ解決式を使う。

        単一段 readlink 版を再導入すると相対 symlink で壊れるため、実装が
        2 系統に分かれないことを固定する。
        """
        weak = re.compile(r'\[\s*-L\s+"\$SCRIPT_PATH"\s*\]')
        expected = 'HOOK_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"'

        sourcing_hooks = []
        for path in sorted(HOOKS.glob("*.sh")):
            text = path.read_text(encoding="utf-8")
            if "lib/" not in text and "/../policy/" not in text:
                continue
            sourcing_hooks.append(path.name)
            # assertNotRegex / assertIn は失敗時に対象文字列（= ファイル全文）を
            # 出力してしまうため、真偽値で比較してメッセージを読める大きさに保つ
            self.assertIsNone(
                weak.search(text), msg=f"{path.name}: 単一段 readlink が復活している"
            )
            self.assertTrue(
                expected in text, msg=f"{path.name}: 共通の解決式を使っていない"
            )

        # 対象がゼロだと検証が空回りするため下限を置く
        self.assertGreaterEqual(len(sourcing_hooks), 10)


if __name__ == "__main__":
    unittest.main()

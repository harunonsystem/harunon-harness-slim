#!/usr/bin/env python3
"""block-grep-in-bash.sh hook のテスト。"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-grep-in-bash.sh"


def _run(command: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TOOL_INPUT"] = json.dumps({"command": command})
    # denial-log.sh の配線テスト（test_denial_log.py）以外は実 ~/.claude/logs/ を
    # 汚染しないよう、deny 記録先を tmp に逃がす。
    env.setdefault(
        "HARNESS_DENIAL_LOG",
        str(Path(tempfile.gettempdir()) / "harness-test-block-grep-denial-log.jsonl"),
    )
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class TestBlockGrepInBash(unittest.TestCase):
    def test_grep_is_blocked(self):
        result = _run("grep foo bar.txt")
        self.assertEqual(result.returncode, 2)

    def test_egrep_is_blocked(self):
        result = _run("egrep foo bar.txt")
        self.assertEqual(result.returncode, 2)

    def test_fgrep_is_blocked(self):
        result = _run("fgrep foo bar.txt")
        self.assertEqual(result.returncode, 2)

    def test_sed_is_blocked(self):
        result = _run("sed 's/foo/bar/' file.txt")
        self.assertEqual(result.returncode, 2)

    def test_awk_is_blocked(self):
        result = _run("awk '{print $1}' file.txt")
        self.assertEqual(result.returncode, 2)

    def test_grep_via_pipe_is_blocked(self):
        result = _run("echo 'hello' | grep foo")
        self.assertEqual(result.returncode, 2)

    def test_grep_via_chain_is_blocked(self):
        result = _run("ls && grep foo bar")
        self.assertEqual(result.returncode, 2)

    def test_rtk_grep_is_allowed(self):
        result = _run("rtk grep foo bar.txt")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_echo_grep_word_is_allowed(self):
        result = _run("echo grep")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_unrelated_command_is_allowed(self):
        result = _run("git log --oneline")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class NormalizedQuoteAwareTestCase(unittest.TestCase):
    """FP-8: 判定を $NORMALIZED に差し替えたことで解消される誤検知。

    旧実装は生コマンド文字列に直接 ERE をかけていたため、quote 内の
    `; grep` のような文字列引数を「起点直後の grep」と誤検知していた。
    危険コマンド判定と同じ正規化を通すことで、quote 内の `;`/`|`/`&&` は
    中和され、起点として扱われなくなる。検体は分割して組み立てる
    （このテストを編集するセッション自身の hook が反応するのを防ぐ規約）。
    """

    GREP = "".join(["g", "r", "e", "p"])

    def test_semicolon_grep_inside_double_quoted_string_is_allowed(self):
        result = _run(f'printf "%s" "note: ; {self.GREP} later"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_grep_word_inside_double_quoted_string_is_allowed(self):
        result = _run(f'echo "please {self.GREP} this"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_and_and_grep_inside_double_quoted_string_is_allowed(self):
        result = _run(f'printf "%s" "a && {self.GREP} b"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_pipe_grep_inside_double_quoted_string_is_allowed(self):
        result = _run(f'printf "%s" "a | {self.GREP} b"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_grep_via_pipe_at_command_position_is_still_blocked(self):
        # 正規化を通しても、実際にコマンド位置にある grep は変わらず deny する。
        result = _run(f"echo 'hello' | {self.GREP} foo")
        self.assertEqual(result.returncode, 2, msg=result.stdout)


if __name__ == "__main__":
    unittest.main()

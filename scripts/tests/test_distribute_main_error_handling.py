#!/usr/bin/env python3
"""distribute.py main() の想定外例外ハンドリング（RVW-003）。

FileNotFoundError/ValueError 以外（KeyError 等）が run() から漏れると main() で
tracebackとともに rc=1 になり、bootstrap --check がこれを「drift」と誤表示していた。
run() から漏れる想定外例外は rc=2（ERROR）に倒す。
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import distribute  # noqa: E402


class MainUnexpectedExceptionTestCase(unittest.TestCase):
    def _run_main_with(self, argv: list[str], side_effect: Exception) -> tuple[int, str]:
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["distribute.py", *argv]), \
                mock.patch.object(distribute, "run", side_effect=side_effect), \
                redirect_stderr(stderr):
            rc = distribute.main()
        return rc, stderr.getvalue()

    def test_key_error_from_run_returns_rc_2(self):
        rc, stderr = self._run_main_with(["claude", "--list"], KeyError("configDir"))
        self.assertEqual(rc, 2)
        self.assertIn("ERROR", stderr)
        self.assertIn("KeyError", stderr)

    def test_known_errors_still_return_rc_2_unchanged(self):
        rc, stderr = self._run_main_with(["claude", "--list"], ValueError("bad target"))
        self.assertEqual(rc, 2)
        self.assertIn("ERROR", stderr)

    def test_harness_debug_env_reraises_instead_of_swallowing(self):
        with mock.patch.dict("os.environ", {"HARNESS_DEBUG": "1"}):
            with mock.patch.object(sys, "argv", ["distribute.py", "claude", "--list"]), \
                    mock.patch.object(distribute, "run", side_effect=KeyError("configDir")):
                with self.assertRaises(KeyError):
                    distribute.main()


if __name__ == "__main__":
    unittest.main()

"""BM25コード探索の公開CLI契約テスト。"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packages/targets/codex/skills/bm25-code-search/scripts/bm25_search.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bm25_search", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module could not be loaded: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BM25CodeSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_tokenize_expands_code_identifiers(self) -> None:
        tokens = self.module.tokenize("ReviewGate.check_review_status")

        self.assertIn("review", tokens)
        self.assertIn("gate", tokens)
        self.assertIn("check", tokens)
        self.assertIn("review", tokens)
        self.assertIn("status", tokens)

    def test_bm25_ranks_relevant_chunk_first(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bm25-search-test-") as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src/auth.py").write_text(
                "def check_review_gate(branch):\n"
                "    return branch != 'main'\n",
                encoding="utf-8",
            )
            (root / "src/render.py").write_text(
                "def render_page(value):\n"
                "    return str(value)\n",
                encoding="utf-8",
            )

            chunks = self.module.build_chunks(root, chunk_lines=20)
            results = self.module.rank_chunks("review gate", chunks, limit=2)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].chunk.path.as_posix(), "src/auth.py")

    def test_ignores_generated_and_binary_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bm25-search-test-") as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "node_modules/pkg").mkdir(parents=True)
            (root / "build").mkdir()
            (root / "src/real.py").write_text("review gate implementation\n", encoding="utf-8")
            (root / "node_modules/pkg/generated.js").write_text(
                "review gate implementation\n", encoding="utf-8"
            )
            (root / "build/generated.py").write_text(
                "review gate implementation\n", encoding="utf-8"
            )
            (root / "src/binary.dat").write_bytes(b"review gate\x00binary")

            chunks = self.module.build_chunks(root, chunk_lines=20)
            paths = {chunk.path.as_posix() for chunk in chunks}

            self.assertEqual(paths, {"src/real.py"})

    def test_cli_emits_bounded_ranked_snippet(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bm25-search-test-") as temp:
            root = Path(temp)
            source = root / "policy.py"
            source.write_text(
                "# unrelated header\n" * 4 + "def review_gate():\n    return True\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "review gate",
                    str(root),
                    "--top-k",
                    "1",
                    "--chunk-lines",
                    "20",
                    "--snippet-lines",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("policy.py", result.stdout)
            self.assertIn("review_gate", result.stdout)
            self.assertLessEqual(len(result.stdout), 3000)


if __name__ == "__main__":
    unittest.main()

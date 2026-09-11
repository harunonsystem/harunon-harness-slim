"""harness_lib.includes と、3 ターゲット間の共有 fragment 一致を検証する。

expandIncludes 方式（additive compose）に移行したことで、共有ブロック
（常駐ルール最小・Routing）は packages/core/fragments/agents-md/ を SSOT とし、
codex / opencode / omp の AGENTS.md がバイト一致で取り込むことを保証する。
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib.includes import expand_includes  # noqa: E402
from harness_lib.resolver import manifest  # noqa: E402


class TestExpandIncludes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "frag").mkdir()
        (self.repo / "frag" / "a.md").write_text("## A\n\n- one\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_marker_replaced_with_fragment(self):
        text = "# T\n\n<!-- include: frag/a.md -->\n\n## next\n"
        out = expand_includes(text, self.repo)
        self.assertEqual(out, "# T\n\n## A\n\n- one\n\n## next\n")
        self.assertNotIn("<!-- include:", out)

    def test_dangling_include_raises(self):
        with self.assertRaises(FileNotFoundError):
            expand_includes("<!-- include: frag/missing.md -->\n", self.repo)

    def test_nested_include_rejected(self):
        (self.repo / "frag" / "b.md").write_text(
            "## B\n<!-- include: frag/a.md -->\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            expand_includes("<!-- include: frag/b.md -->\n", self.repo)

    def test_absolute_and_parent_path_rejected(self):
        with self.assertRaises(ValueError):
            expand_includes("<!-- include: /etc/passwd -->\n", self.repo)
        with self.assertRaises(ValueError):
            expand_includes("<!-- include: ../secret.md -->\n", self.repo)

    def test_non_include_comment_untouched(self):
        text = "<!-- just a comment -->\n"
        self.assertEqual(expand_includes(text, self.repo), text)

    def test_symlink_escaping_the_repo_is_rejected(self):
        """repo 内の symlink 経由で repo 外を読めてはいけない。

        文字列検査（絶対パス・'..'）は通ってしまうため、実体パスまで確認する。
        通すと配布物へ repo 外の内容（~/.ssh や API key）が埋め込まれる。
        """
        outside = Path(self._tmp.name).parent / "outside-secret.md"
        outside.write_text("SECRET\n", encoding="utf-8")
        try:
            link = self.repo / "frag" / "link.md"
            link.symlink_to(outside)
            with self.assertRaises(ValueError) as ctx:
                expand_includes("<!-- include: frag/link.md -->\n", self.repo)
            self.assertIn("外を指しています", str(ctx.exception))
        finally:
            outside.unlink(missing_ok=True)

    def test_symlink_inside_the_repo_is_allowed(self):
        # repo 内に閉じた symlink は従来どおり使える（過剰に締めない）
        link = self.repo / "frag" / "inner.md"
        link.symlink_to(self.repo / "frag" / "a.md")
        self.assertIn("## A", expand_includes("<!-- include: frag/inner.md -->\n", self.repo))


class TestSharedFragmentsAcrossTargets(unittest.TestCase):
    """3 ターゲットの AGENTS.md が同一の共有 fragment を取り込んでいること。"""

    def _extract_section(self, text: str, heading: str) -> str:
        lines = text.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.strip() == heading)
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        return "\n".join(lines[start:end]).rstrip()

    def test_minimal_rules_identical(self):
        outs = {
            t: manifest(t, REPO_ROOT).files["AGENTS.md"].decode("utf-8")
            for t in ("codex", "opencode", "omp")
        }
        rules = {
            t: self._extract_section(o, "## 常駐ルール（最小）") for t, o in outs.items()
        }
        self.assertEqual(rules["codex"], rules["opencode"])
        self.assertEqual(rules["codex"], rules["omp"])

    def test_routing_identical(self):
        outs = {
            t: manifest(t, REPO_ROOT).files["AGENTS.md"].decode("utf-8")
            for t in ("codex", "opencode", "omp")
        }
        routing = {
            t: self._extract_section(o, "## Routing（必要時にだけ読む）")
            for t, o in outs.items()
        }
        self.assertEqual(routing["codex"], routing["opencode"])
        self.assertEqual(routing["codex"], routing["omp"])

    def test_fragments_are_source_only_not_distributed(self):
        for t in ("codex", "opencode", "omp"):
            files = manifest(t, REPO_ROOT).files
            self.assertFalse(
                any("fragments/" in k for k in files),
                msg=f"{t}: fragment は配布物に含めない（source-only）",
            )


if __name__ == "__main__":
    unittest.main()

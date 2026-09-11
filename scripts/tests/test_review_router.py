#!/usr/bin/env python3
"""review-router.sh の review_route() 分類テスト。

lib 単体を bash -c で source して直接呼び出す（hook を経由しない）。
分類優先順位: none > bypass > difit > review。
"""
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROUTER_LIB = REPO_ROOT / "packages" / "core" / "hooks" / "lib" / "review-router.sh"


def _route(name_status: str, numstat_total: int = 0, commit_subjects: str = "") -> str:
    """review_route() を呼び出し、route 文字列を返す。"""
    script = f'source "{ROUTER_LIB}"; review_route {numstat_total} "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", commit_subjects],
        input=name_status,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestReviewRouteNone(unittest.TestCase):
    def test_all_markdown_files_is_none(self):
        diff = "M\tdocs/plan.md\nA\tCONTEXT.md"
        self.assertEqual(_route(diff), "none")

    def test_all_files_under_docs_dir_is_none(self):
        diff = "M\tdocs/adr/001-foo.txt\nA\tdocs/plans/002-bar.mdx"
        self.assertEqual(_route(diff), "none")

    def test_all_files_under_rules_dir_is_none(self):
        diff = "M\tpackages/core/rules/core-standards.md"
        self.assertEqual(_route(diff), "none")

    def test_code_file_under_docs_dir_is_review(self):
        # docs/ 配下でもコード拡張子はレビュー必須（SSOT「Markdown のみ免除」）
        diff = "M\tdocs/gen.ts"
        self.assertEqual(_route(diff), "review")


class TestReviewRouteBypass(unittest.TestCase):
    def test_all_lockfiles_is_bypass(self):
        diff = "M\tpnpm-lock.yaml"
        self.assertEqual(_route(diff), "bypass")

    def test_mixed_lockfile_basenames_is_bypass(self):
        diff = "M\tpnpm-lock.yaml\nM\tpackages/other/yarn.lock"
        self.assertEqual(_route(diff), "bypass")

    def test_all_snapshot_dir_files_is_bypass(self):
        diff = "A\tsrc/components/Foo/__snapshots__/Foo.test.tsx.snap"
        self.assertEqual(_route(diff), "bypass")

    def test_all_snap_extension_files_is_bypass(self):
        diff = "A\tsrc/__snapshots__/foo.snap\nM\tsrc/bar.snap"
        self.assertEqual(_route(diff), "bypass")

    def test_all_generated_dir_files_is_bypass(self):
        diff = "A\tsrc/apis/v2/generated/top/top.msw.ts\nM\tsrc/apis/v2/generated/schemas/foo.ts"
        self.assertEqual(_route(diff), "bypass")

    def test_all_revert_commit_subjects_is_bypass_even_for_code_files(self):
        diff = "M\tsrc/foo.ts"
        subjects = "Revert \"add foo\"\nRevert \"fix bar\""
        self.assertEqual(_route(diff, commit_subjects=subjects), "bypass")

    def test_mixed_bypass_and_code_file_is_not_bypass(self):
        """bypass 判定は「全ファイルが」が条件。1 つでも code ファイルが混じれば bypass ではない。"""
        diff = "M\tpnpm-lock.yaml\nM\tsrc/foo.ts"
        self.assertNotEqual(_route(diff), "bypass")


class TestReviewRouteDifit(unittest.TestCase):
    def test_file_count_at_threshold_is_difit(self):
        diff = "\n".join(f"M\tsrc/file{i}.ts" for i in range(10))
        self.assertEqual(_route(diff), "difit")

    def test_file_count_below_threshold_is_not_difit(self):
        diff = "\n".join(f"M\tsrc/file{i}.ts" for i in range(9))
        self.assertEqual(_route(diff), "review")

    def test_line_count_at_threshold_is_difit(self):
        diff = "M\tsrc/foo.ts"
        self.assertEqual(_route(diff, numstat_total=400), "difit")

    def test_line_count_below_threshold_is_not_difit(self):
        diff = "M\tsrc/foo.ts"
        self.assertEqual(_route(diff, numstat_total=399), "review")

    def test_components_dir_file_is_difit_regardless_of_size(self):
        diff = "M\tsrc/components/Button/Button.tsx"
        self.assertEqual(_route(diff, numstat_total=1), "difit")

    def test_designsystems_dir_file_is_difit_regardless_of_size(self):
        diff = "A\tsrc/designsystems/ui/Badge.tsx"
        self.assertEqual(_route(diff, numstat_total=1), "difit")


class TestReviewRouteReview(unittest.TestCase):
    def test_mixed_code_and_docs_is_review(self):
        diff = "M\tsrc/foo.ts\nM\tdocs/plan.md"
        self.assertEqual(_route(diff), "review")

    def test_small_code_only_change_is_review(self):
        diff = "M\tsrc/foo.ts"
        self.assertEqual(_route(diff, numstat_total=50), "review")

    def test_empty_diff_is_review(self):
        self.assertEqual(_route(""), "review")

    def test_rename_line_uses_new_path_for_classification(self):
        """git diff --name-status の rename は 'R100\\told\\tnew' 形式（最終列が新パス）。"""
        diff = "R100\told/src/foo.ts\tnew/src/components/foo.tsx"
        self.assertEqual(_route(diff), "difit")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""外部 skill (rulesync curated) の distribution ledger 統合テスト（ADR-011 Update 2026-08-30）。

curated skill は distribute["skills/"].source に .rulesync/skills/.curated/ を
追加した通常の manifest エントリになる。ここでは --check の drift 検出と
--push --prune による退役分の削除を、旧 bootstrap Step 2.5 の bash rm -rf の
代わりとして固定する。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness_lib.distribution_state import LEDGER_FILENAME  # noqa: E402
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


def _write_curated_skill(repo: Path, name: str, body: str) -> None:
    skill_dir = repo / ".rulesync" / "skills" / ".curated" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def _write_lock(repo: Path, names: list[str]) -> None:
    (repo / "rulesync.lock").write_text(
        json.dumps({"sources": {"demo/skills": {"skills": {n: {} for n in names}}}}),
        encoding="utf-8",
    )


class CuratedSkillsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        self.live = self.repo / "live/claude"
        self.live.mkdir(parents=True)

        config = self.repo / "packages/targets/claude/config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["distribute"]["skills/"]["source"].append(".rulesync/skills/.curated/")
        config.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def push(self, *extra: str) -> tuple[int, str]:
        return run_distribute_cli([
            "claude", "--push", "--live", str(self.live),
            "--repo-root", str(self.repo), *extra,
        ])

    def ledger(self) -> dict:
        return json.loads((self.live / LEDGER_FILENAME).read_text(encoding="utf-8"))

    def check(self) -> tuple[int, str]:
        return run_distribute_cli([
            "claude", "--check", "--live", str(self.live),
            "--repo-root", str(self.repo),
        ])

    def test_curated_skill_is_pushed_like_any_managed_file(self) -> None:
        _write_lock(self.repo, ["demo-curated"])
        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\nbody\n")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertTrue((self.live / "skills/demo-curated/SKILL.md").is_file())

    def test_check_detects_curated_drift(self) -> None:
        _write_lock(self.repo, ["demo-curated"])
        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\nv1\n")
        self.push()

        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\nv2\n")
        code, output = self.check()

        self.assertEqual(code, 1, msg=output)
        self.assertIn("skills/demo-curated/SKILL.md", output)

    def test_push_prune_removes_retired_curated_skill(self) -> None:
        _write_lock(self.repo, ["demo-curated"])
        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\n")
        self.push()
        self.assertTrue((self.live / "skills/demo-curated/SKILL.md").is_file())

        # upstream/lock から retired: 宣言と実体を両方消す
        _write_lock(self.repo, [])
        import shutil
        shutil.rmtree(self.repo / ".rulesync/skills/.curated/demo-curated")

        code, output = self.push("--prune")

        self.assertEqual(code, 0, msg=output)
        self.assertFalse((self.live / "skills/demo-curated").exists())

    def test_undeclared_leftover_in_curated_dir_is_not_distributed(self) -> None:
        """rulesync.jsonc から外した skill の残骸（.curated に残るが lock に無い）は配らない。"""
        _write_lock(self.repo, ["demo-curated"])
        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\n")
        _write_curated_skill(self.repo, "stale-skill", "---\nname: stale-skill\n---\n")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertTrue((self.live / "skills/demo-curated/SKILL.md").is_file())
        self.assertFalse((self.live / "skills/stale-skill").exists())

    def test_missing_lock_declared_skill_fails_closed(self) -> None:
        """rulesync.lock に宣言されているのに .curated に無い skill は push を止める。"""
        _write_lock(self.repo, ["demo-curated", "missing-skill"])
        _write_curated_skill(self.repo, "demo-curated", "---\nname: demo-curated\n---\n")

        code, output = self.push()

        self.assertNotEqual(code, 0, msg=output)
        self.assertIn("missing-skill", output)

    def test_curated_dir_absent_skips_without_error(self) -> None:
        """rulesync install 未実行（.rulesync/skills/.curated/ 自体が無い）は push を止めない。"""
        _write_lock(self.repo, ["demo-curated"])

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertFalse((self.live / "skills/demo-curated").exists())

    def test_stale_file_inside_still_declared_curated_skill_is_removed_on_push(self) -> None:
        """skill 自体は rulesync.lock に残ったまま、upstream がその中の1ファイルだけ
        削除したケース。旧 hand-over 分離は skills/<curated-name>/... を丸ごと ledger
        から外してしまい、この stale file を「保護」も「削除」もせず live に残し続ける
        バグがあった。今はここも通常の stale-managed 経路で拾われる。"""
        _write_lock(self.repo, ["demo-curated"])
        skill_dir = self.repo / ".rulesync/skills/.curated/demo-curated"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: demo-curated\n---\n", encoding="utf-8")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "old.md").write_text("old\n", encoding="utf-8")
        self.push()
        self.assertTrue((self.live / "skills/demo-curated/references/old.md").is_file())

        # upstream が references/old.md を削除。skill 自体は lock に残る。
        (skill_dir / "references" / "old.md").unlink()

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertIn("[removed-managed] skills/demo-curated/references/old.md", output)
        self.assertFalse((self.live / "skills/demo-curated/references/old.md").exists())
        self.assertTrue((self.live / "skills/demo-curated/SKILL.md").is_file())
        self.assertNotIn(
            "skills/demo-curated/references/old.md", self.ledger()["files"]
        )

    def test_check_detects_stale_file_inside_still_declared_curated_skill(self) -> None:
        _write_lock(self.repo, ["demo-curated"])
        skill_dir = self.repo / ".rulesync/skills/.curated/demo-curated"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: demo-curated\n---\n", encoding="utf-8")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "old.md").write_text("old\n", encoding="utf-8")
        self.push()

        (skill_dir / "references" / "old.md").unlink()

        code, output = self.check()

        self.assertEqual(code, 1, msg=output)
        self.assertIn("skills/demo-curated/references/old.md", output)

    def test_pull_does_not_write_into_curated_cache_and_warns(self) -> None:
        """curated source は SSOT ではない（upstream が正本）。live 側の編集を
        --pull で .rulesync/skills/.curated/ に書き戻してはいけない。"""
        _write_lock(self.repo, ["demo-curated"])
        skill_dir = self.repo / ".rulesync/skills/.curated/demo-curated"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: demo-curated\n---\nv1\n", encoding="utf-8")
        self.push()

        (self.live / "skills/demo-curated/SKILL.md").write_text(
            "---\nname: demo-curated\n---\nlive edit\n", encoding="utf-8"
        )

        code, output = run_distribute_cli([
            "claude", "--pull", "--live", str(self.live), "--repo-root", str(self.repo),
        ])

        self.assertEqual(code, 0, msg=output)
        self.assertEqual(
            (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
            "---\nname: demo-curated\n---\nv1\n",
            "pull が curated cache を上書きしてはいけない",
        )
        self.assertIn("skills/demo-curated/SKILL.md", output)


if __name__ == "__main__":
    unittest.main()

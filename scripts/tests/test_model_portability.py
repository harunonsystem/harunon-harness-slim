from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib.validators.model_portability import check  # noqa: E402


def _write_json(root: Path, relative_path: str, value: object) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_table(root: Path, *, models: dict[str, str], routes: list[dict] | None = None) -> None:
    table: dict[str, object] = {"models": models}
    if routes is not None:
        table["routes"] = routes
    _write_json(root, "packages/core/model-routing.json", table)


class TestModelPortability(unittest.TestCase):
    def test_model_id_in_portable_doc_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            path = root / "packages/core/rules/core.md"
            path.parent.mkdir(parents=True)
            path.write_text("use gpt-5.6-edge here\n", encoding="utf-8")

            findings = check(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("packages/core/rules/core.md", findings[0].message)
            self.assertIn("gpt-5.6-edge", findings[0].message)

    def test_model_id_in_portable_skill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            path = root / "packages/core/skills/demo/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("use gpt-5.6-edge here\n", encoding="utf-8")

            findings = check(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("packages/core/skills/demo/SKILL.md", findings[0].message)

    def test_model_id_in_target_agent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            path = root / "packages/targets/demo/AGENTS.md"
            path.parent.mkdir(parents=True)
            path.write_text("use gpt-5.6-edge here\n", encoding="utf-8")

            findings = check(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("packages/targets/demo/AGENTS.md", findings[0].message)

    def test_model_id_in_target_edge_skill_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            _write_json(root, "packages/core/disabled-skills.json", {"common": ["edge-skill"]})
            path = root / "packages/core/skills/edge-skill/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("use gpt-5.6-edge here\n", encoding="utf-8")

            self.assertEqual(check(root), [])


    def test_model_id_in_edge_doc_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            path = root / "packages/core/CLAUDE.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("use gpt-5.6-edge here\n", encoding="utf-8")

            self.assertEqual(check(root), [])

    def test_projection_requires_target_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projection = "packages/targets/codex/profiles/review.config.toml"
            route = {"runtime": "codex", "projections": [{"path": projection}]}
            _write_table(root, models={"edge": "gpt-5.6-edge"}, routes=[route])
            _write_json(
                root,
                "packages/targets/codex/config.json",
                {"distribute": {"review": {"source": "packages/targets/codex/other.toml"}}},
            )

            findings = check(root)
            self.assertEqual(len(findings), 1)
            self.assertIn(projection, findings[0].message)
            self.assertIn("socket", findings[0].message)

            _write_json(
                root,
                "packages/targets/codex/config.json",
                {"distribute": {"review": {"source": projection}}},
            )
            self.assertEqual(check(root), [])

    def test_malformed_target_config_is_reported_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_table(root, models={"edge": "gpt-5.6-edge"})
            _write_json(root, "packages/targets/codex/config.json", [])

            findings = check(root)

            self.assertEqual(len(findings), 1)
            self.assertIn("packages/targets/codex/config.json", findings[0].message)
            self.assertIn("root", findings[0].message)


if __name__ == "__main__":
    unittest.main()

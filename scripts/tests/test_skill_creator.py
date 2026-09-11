"""Skill packaging validates the frontmatter used by supported runtimes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packages/core/skills/skill-creator/scripts/quick_validate.py"
spec = importlib.util.spec_from_file_location("skill_quick_validate", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class TestSkillCreatorFrontmatter(unittest.TestCase):
    def test_existing_runtime_frontmatter_is_valid(self):
        for name in ("run-change", "decompose-issues", "grill-me", "pre-review-check"):
            with self.subTest(skill=name):
                valid, reason = validator.validate_skill(REPO_ROOT / "packages/core/skills" / name)
                self.assertTrue(valid, reason)

    def test_empty_required_fields_are_invalid(self):
        for field in ("name", "description"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "example"
                root.mkdir()
                values = {"name": "example", "description": "Create an example."}
                values[field] = ""
                (root / "SKILL.md").write_text(
                    f'---\nname: "{values["name"]}"\ndescription: "{values["description"]}"\n---\n'
                )
                valid, _ = validator.validate_skill(root)
                self.assertFalse(valid)

#!/usr/bin/env python3
"""publish-public-slim.sh の publish 経路のテスト。

verify は slim 全体のテストスイートを回すので重く、ここでは扱わない（CI の publish-slim.yml と
ローカルの `scripts/publish-public-slim.sh verify` が担う）。publish は --remote-base でローカル
bare repo に向け、--skip-verify で用意した生成物ディレクトリをそのまま配る。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/publish-public-slim.sh"
MANIFEST = json.loads((REPO_ROOT / "packages/public-slim/manifest.json").read_text(encoding="utf-8"))


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class TestPublishPublicSlim(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="publish-slim-test.")
        root = Path(self._tmp.name)
        self.output = root / "out"
        self.remote_base = root / "remotes"
        self.bare: dict[str, Path] = {}
        for name, spec in MANIFEST["publish"].items():
            (self.output / name).mkdir(parents=True)
            (self.output / name / "README.md").write_text(f"# {name}\n", encoding="utf-8")
            (self.output / name / "payload.txt").write_text("v1\n", encoding="utf-8")
            bare = self.remote_base / f"{spec['repo']}.git"
            bare.parent.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "--bare", str(bare))
            self.bare[name] = bare

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *extra: str, env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(
            [str(SCRIPT), "publish", "--skip-verify", "--output", str(self.output),
             "--remote-base", str(self.remote_base), *extra],
            cwd=REPO_ROOT, capture_output=True, text=True, errors="replace",
            timeout=120, env=full_env,
        )

    def _head(self, name: str) -> str | None:
        branch = MANIFEST["publish"][name]["branch"]
        result = subprocess.run(
            ["git", "-C", str(self.bare[name]), "rev-parse", f"refs/heads/{branch}"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def test_publishes_each_output_to_its_declared_repo(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        for name in MANIFEST["publish"]:
            head = self._head(name)
            self.assertIsNotNone(head, msg=name)
            tree = _git("-C", str(self.bare[name]), "ls-tree", "--name-only", head)
            self.assertEqual(sorted(tree.splitlines()), ["README.md", "payload.txt"])
            subject = _git("-C", str(self.bare[name]), "log", "-1", "--format=%s", head)
            self.assertTrue(subject.startswith("Regenerate from harunon-harness@"), msg=subject)

    def test_rerun_without_changes_pushes_nothing(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        heads = {name: self._head(name) for name in MANIFEST["publish"]}
        second = self._run()
        self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
        self.assertIn("no changes; skip", second.stdout)
        self.assertEqual({name: self._head(name) for name in MANIFEST["publish"]}, heads)

    def test_dry_run_shows_diff_but_does_not_push(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        heads = {name: self._head(name) for name in MANIFEST["publish"]}
        for name in MANIFEST["publish"]:
            (self.output / name / "payload.txt").write_text("v2\n", encoding="utf-8")
        result = self._run("--dry-run")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("payload.txt", result.stdout)
        self.assertIn("dry-run", result.stdout)
        self.assertEqual({name: self._head(name) for name in MANIFEST["publish"]}, heads)

    def test_update_is_pushed_on_top_of_existing_branch(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        name = next(iter(MANIFEST["publish"]))
        first = self._head(name)
        (self.output / name / "payload.txt").write_text("v2\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        second = self._head(name)
        self.assertNotEqual(first, second)
        self.assertEqual(_git("-C", str(self.bare[name]), "rev-parse", f"{second}^"), first)

    def test_deploy_token_is_never_printed(self) -> None:
        result = self._run(env={"SLIM_DEPLOY_TOKEN": "dummy-secret-token-value"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotIn("dummy-secret-token-value", result.stdout + result.stderr)

    def test_output_dir_without_publish_declaration_fails(self) -> None:
        (self.output / "unknown-slim").mkdir()
        (self.output / "unknown-slim" / "x.txt").write_text("x\n", encoding="utf-8")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown-slim", result.stderr)

    def test_manifest_declares_both_distributions(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib import public_slim

        self.assertEqual(
            set(MANIFEST["publish"]),
            {public_slim.HARNESS_SLIM_DIR, public_slim.PI_AGENT_SLIM_DIR},
        )

    def test_unknown_argument_is_rejected(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--bogus"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)


if __name__ == "__main__":
    unittest.main()

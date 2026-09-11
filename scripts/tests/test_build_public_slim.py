#!/usr/bin/env python3
"""public slim 配布物（harunon-harness-slim / harunon-pi-agent-slim）の build とゲートのテスト。

build は SSOT 全体を読むので、クラス単位で 1 回だけ生成して共有する（1 回 ~5 秒）。
ゲートの fail-close / hit 検出は生成物を触らず harness_lib.public_slim を直接叩く。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts/build-public-slim.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib import public_slim  # noqa: E402
from harness_lib.includes import INCLUDE_RE  # noqa: E402


def _env_file_with_terms(directory: Path, terms: str) -> Path:
    env = directory / ".env"
    env.write_text(f"CODENAME=example\n{public_slim.BLOCKED_TERMS_KEY}={terms}\n", encoding="utf-8")
    return env


class TestBuildPublicSlim(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="public-slim-test.")
        cls.output = Path(cls.tmp.name) / "out"
        # 実 .env に依存しない: テスト専用の env file を渡して fail-close を回避する。
        # 語は実行時に作る（固定文字列だと、このテストファイル自身が slim に含まれて自己ヒットする）
        cls.env_file = _env_file_with_terms(Path(cls.tmp.name), f"zz-{uuid.uuid4().hex}")
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--output", str(cls.output), "--env-file", str(cls.env_file)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.stdout = result.stdout
        cls.harness = cls.output / public_slim.HARNESS_SLIM_DIR
        cls.pi = cls.output / public_slim.PI_AGENT_SLIM_DIR
        cls.manifest = public_slim.load_manifest(REPO_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    # --- harness-slim ---------------------------------------------------

    def test_excluded_paths_are_absent_and_included_present(self) -> None:
        # addFiles で置き直す dest（lessons.json の空 ledger）は exclude でも存在してよい
        replaced = set(self.manifest["addFiles"])
        for rel in self.manifest["exclude"]:
            if rel in replaced:
                continue
            self.assertFalse((self.harness / rel).exists(), msg=rel)
        for rel in ("packages/core/CLAUDE.md", "scripts/distribute.py", "packages/targets/pi/config.json"):
            self.assertTrue((self.harness / rel).is_file(), msg=rel)
        # hook 実体は残す（manifest.keptTooling）
        self.assertTrue((self.harness / "packages/core/hooks/rtk-rewrite.sh").is_file())

    def test_add_files_are_placed(self) -> None:
        for dest in self.manifest["addFiles"]:
            self.assertTrue((self.harness / dest).is_file(), msg=dest)
        self.assertIn("MIT License", (self.harness / "LICENSE").read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((self.harness / "packages/core/lessons/lessons.json").read_text(encoding="utf-8")), []
        )

    def test_dangling_include_lines_are_dropped(self) -> None:
        text = (self.harness / "packages/core/CLAUDE.md").read_text(encoding="utf-8")
        for m in INCLUDE_RE.finditer(text):
            self.assertTrue((self.harness / m.group("path")).is_file(), msg=m.group("path"))
        self.assertNotIn("fragments/claude-md/", text)

    def test_excluded_distribute_sources_are_dropped_from_target_configs(self) -> None:
        for config in sorted((self.harness / "packages/targets").glob("*/config.json")):
            cfg = json.loads(config.read_text(encoding="utf-8"))
            distribute = cfg.get("distribute") or {}
            self.assertNotIn("RTK.md", distribute, msg=config.name)
            for key, spec in distribute.items():
                sources = spec["source"] if isinstance(spec["source"], list) else [spec["source"]]
                for source in sources:
                    # SSOT にも無い source（bootstrap が取得する curated）は残ってよい
                    if not (REPO_ROOT / source).exists():
                        continue
                    self.assertTrue((self.harness / source).exists(), msg=f"{config.parent.name}: {key} -> {source}")
        # curated の source は残る（rulesync.lock を含めるので slim でも bootstrap が取得できる）
        claude_cfg = json.loads((self.harness / "packages/targets/claude/config.json").read_text(encoding="utf-8"))
        self.assertIn(".rulesync/skills/.curated/", claude_cfg["distribute"]["skills/"]["source"])
        # tab インデントを維持（SSOT との diff が読める）
        raw = (self.harness / "packages/targets/pi/config.json").read_text(encoding="utf-8")
        self.assertTrue(raw.splitlines()[1].startswith("\t"))

    def test_ghost_command_rows_are_dropped(self) -> None:
        from harness_lib.validators.skills import (
            BUILTIN_COMMANDS,
            _extract_commands_from_commands_md,
            harness_skill_names,
        )

        from harness_lib.curated_skills import list_curated_skills

        commands_md = self.harness / "packages/core/commands.md"
        known = harness_skill_names(self.harness) | list_curated_skills(self.harness) | BUILTIN_COMMANDS
        ghosts = _extract_commands_from_commands_md(commands_md) - known
        self.assertEqual(ghosts, set())
        # curated（rulesync.lock 宣言）の行は残す。落とすと CLAUDE.md / rules の /tdd 等が dangling になる
        self.assertIn("`/tdd`", commands_md.read_text(encoding="utf-8"))

    def test_instruction_docs_do_not_reference_excluded_dependencies(self) -> None:
        # build が verifyReferences で検証済み。ここでは AGENTS.md の RTK 行と CLAUDE.md の fragment を直接見る
        for target in ("codex", "pi", "omp", "opencode"):
            text = (self.harness / f"packages/targets/{target}/AGENTS.md").read_text(encoding="utf-8")
            self.assertNotIn("routing-rtk.md", text, msg=target)
            self.assertIn("routing-browser.md", text, msg=target)
        self.assertFalse((self.harness / "packages/core/fragments/agents-md/routing-rtk.md").exists())

    def test_verify_references_rejects_dangling_skill_and_excluded_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "packages/core/skills").mkdir(parents=True)
            (out / "packages/core/CLAUDE.md").write_text("use `/nonexistent-skill` here\n", encoding="utf-8")
            with self.assertRaises(public_slim.SlimBuildError) as ctx:
                public_slim._verify_references(out)
            self.assertIn("/nonexistent-skill", str(ctx.exception))
            (out / "packages/core/CLAUDE.md").write_text("read RTK.md for savings\n", encoding="utf-8")
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim._verify_references(out)
            (out / "packages/core/CLAUDE.md").write_text("nothing dangling; `/tmp` is a path\n", encoding="utf-8")
            public_slim._verify_references(out)  # 通る

    # --- allowlist / enumeration boundaries -----------------------------

    def test_allowlist_file_entries_match_exactly_and_dirs_by_prefix(self) -> None:
        files = ["CLAUDE.md", "CLAUDE.md.private", "scripts/a.py", "scripts2/b.py", "scripts/tests/x"]
        manifest = {"include": ["CLAUDE.md", "scripts/"], "exclude": ["scripts/tests/"]}
        self.assertEqual(public_slim.select_files(files, manifest), ["CLAUDE.md", "scripts/a.py"])

    def test_enumerate_files_fails_closed_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim.enumerate_files(root)
            self.assertEqual(public_slim.enumerate_files(root, allow_walk=True), ["a.txt"])
            # .git はあるが git が読めない tree は walk に落とさず fail-close
            (root / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim.enumerate_files(root)

    def test_tracked_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "pub").mkdir(parents=True)
            (repo / "pub/ok.txt").write_text("ok", encoding="utf-8")
            outside = Path(tmp) / "secret.txt"
            outside.write_text("secret", encoding="utf-8")
            (repo / "pub/leak.txt").symlink_to(outside)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            manifest = {"include": ["pub/"], "exclude": []}
            with self.assertRaises(public_slim.SlimBuildError) as ctx:
                public_slim.build_harness_slim(repo, manifest, Path(tmp) / "out")
            self.assertIn("pub/leak.txt", str(ctx.exception))

    def test_only_harness_does_not_leave_stale_pi_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            stale = out / public_slim.PI_AGENT_SLIM_DIR
            stale.mkdir(parents=True)
            (stale / "stale.txt").write_text("old", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--output", str(out), "--only", "harness", "--env-file", str(self.env_file)],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertFalse(stale.exists())
            self.assertTrue((out / public_slim.HARNESS_SLIM_DIR / "LICENSE").is_file())

    def test_pi_payload_contains_only_distributed_and_slim_static_files(self) -> None:
        # private tree の packages/public-slim/pi-agent/ から直接コピーしない（.gitignore 対象の
        # ローカル成果物が allowlist を通らずに混入する経路）。payload の非配布ファイルは全て
        # harness-slim 側の静的ディレクトリに実体がある
        install_manifest = json.loads((self.pi / public_slim.INSTALL_MANIFEST_NAME).read_text(encoding="utf-8"))
        managed = [p for p in install_manifest["managedPaths"]]
        static_root = self.harness / public_slim.PI_AGENT_STATIC_REL
        for path in self.pi.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.pi).as_posix()
            if rel == public_slim.INSTALL_MANIFEST_NAME:
                continue
            if any(rel == m or rel.startswith(m.rstrip("/") + "/") for m in managed):
                continue
            self.assertTrue((static_root / rel).is_file(), msg=f"payload に出自不明のファイル: {rel}")

    def test_copy_helper_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            root.mkdir()
            (root / "real.txt").write_text("x", encoding="utf-8")
            (root / "link.txt").symlink_to(root / "real.txt")
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim._copy_file_no_symlink(root, "link.txt", Path(tmp) / "out/link.txt")
            public_slim._copy_file_no_symlink(root, "real.txt", Path(tmp) / "out/real.txt")
            self.assertTrue((Path(tmp) / "out/real.txt").is_file())

    def test_pi_install_dry_run_writes_nothing(self) -> None:
        if shutil.which("jq") is None or shutil.which("rsync") is None:
            self.skipTest("jq / rsync が無い")
        dest = Path(self.tmp.name) / "pi-dry-run-dest"
        result = subprocess.run(
            [str(self.pi / "scripts/install.sh"), "--dest", str(dest), "--dry-run"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertFalse(dest.exists())
        self.assertIn("A settings.json", result.stdout)

    def test_pi_install_prunes_files_retired_from_payload(self) -> None:
        if shutil.which("jq") is None or shutil.which("rsync") is None:
            self.skipTest("jq / rsync が無い")
        payload = Path(self.tmp.name) / "pi-payload-copy"
        shutil.copytree(self.pi, payload)
        dest = Path(self.tmp.name) / "pi-prune-dest"
        install = payload / "scripts/install.sh"
        self.assertEqual(subprocess.run([str(install), "--dest", str(dest)], capture_output=True, text=True, timeout=120).returncode, 0)
        retired = "rules/visual-design.md"
        self.assertTrue((dest / retired).is_file())
        ledger = json.loads((dest / ".harunon-pi-agent-slim.installed.json").read_text(encoding="utf-8"))
        self.assertIn(retired, ledger["files"])
        # 管理外のローカルファイルは ledger に無いので触られない
        (dest / "extensions/local-only.js").write_text("// mine\n", encoding="utf-8")
        (payload / retired).unlink()
        check = subprocess.run([str(install), "--dest", str(dest), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(check.returncode, 1, msg=check.stdout)
        self.assertIn(f"D {retired}", check.stdout)
        dry = subprocess.run([str(install), "--dest", str(dest), "--dry-run"], capture_output=True, text=True, timeout=120)
        self.assertIn(f"D {retired}", dry.stdout)
        self.assertTrue((dest / retired).is_file())  # dry-run では消さない
        second = subprocess.run([str(install), "--dest", str(dest)], capture_output=True, text=True, timeout=120)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertFalse((dest / retired).exists())
        self.assertTrue((dest / "extensions/local-only.js").is_file())
        final = subprocess.run([str(install), "--dest", str(dest), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(final.returncode, 0, msg=final.stdout + final.stderr)

    def test_gate_redacts_blocked_term_in_reported_path(self) -> None:
        self.assertEqual(public_slim.redact("docs/Acme-Corp-notes.md", "acme-corp"), "docs/***-notes.md")
        rendered = public_slim.render_gate(
            public_slim.GateResult(pattern_count=1, hits={"acme-corp": ["slim/docs/acme-corp.md"]}, suspicious={})
        )
        self.assertNotIn("acme-corp", rendered)
        self.assertIn("***", rendered)

    def test_context_scale_counts_match_slim_tree(self) -> None:
        from harness_lib.validators.context_md import check_context_scale_counts

        self.assertEqual(check_context_scale_counts(self.harness), [])

    def test_slim_tree_lists_every_target(self) -> None:
        for config in sorted((self.harness / "packages/targets").glob("*/config.json")):
            target = config.parent.name
            result = subprocess.run(
                [sys.executable, str(self.harness / "scripts/distribute.py"), target, "--list"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, msg=f"{target}: {result.stderr}")

    # --- pi-agent-slim --------------------------------------------------

    def test_pi_payload_has_install_manifest_and_no_private_content(self) -> None:
        install_manifest = json.loads((self.pi / public_slim.INSTALL_MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertIn("AGENTS.md", install_manifest["managedPaths"])
        self.assertIn("settings.json", install_manifest["managedPaths"])
        self.assertTrue(install_manifest["settingsKeys"])
        for path in install_manifest["managedPaths"]:
            self.assertTrue((self.pi / path).exists(), msg=path)
        self.assertFalse((self.pi / "RTK.md").exists())
        for name in public_slim.DISTRIBUTE_STATE_ARTIFACTS:
            self.assertFalse((self.pi / name).exists(), msg=name)
        for rel in ("scripts/install.sh", "scripts/validate.sh", "README.md", ".gitignore"):
            self.assertTrue((self.pi / rel).is_file(), msg=rel)
        self.assertTrue(os.access(self.pi / "scripts/install.sh", os.X_OK))

    def test_pi_install_script_round_trips(self) -> None:
        if shutil.which("jq") is None or shutil.which("rsync") is None:
            self.skipTest("jq / rsync が無い")
        dest = Path(self.tmp.name) / "pi-dest"
        install = self.pi / "scripts/install.sh"
        first = subprocess.run([str(install), "--dest", str(dest)], capture_output=True, text=True, timeout=120)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertTrue((dest / "AGENTS.md").is_file())
        check = subprocess.run([str(install), "--dest", str(dest), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(check.returncode, 0, msg=check.stdout + check.stderr)
        # ローカル専用キーは保持され、管理キーだけが SSOT に揃う
        settings = dest / "settings.json"
        local = json.loads(settings.read_text(encoding="utf-8"))
        local["localOnlyKey"] = "keep-me"
        local["theme"] = "changed-locally"
        settings.write_text(json.dumps(local), encoding="utf-8")
        drift = subprocess.run([str(install), "--dest", str(dest), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(drift.returncode, 1, msg=drift.stdout)
        second = subprocess.run([str(install), "--dest", str(dest)], capture_output=True, text=True, timeout=120)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        merged = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(merged["localOnlyKey"], "keep-me")
        self.assertNotEqual(merged["theme"], "changed-locally")

    # --- gate -----------------------------------------------------------

    def test_gate_passes_and_reports_pattern_count(self) -> None:
        self.assertIn("hits: none", self.stdout)
        result = public_slim.run_gate(
            REPO_ROOT, self.manifest,
            {public_slim.HARNESS_SLIM_DIR: self.harness, public_slim.PI_AGENT_SLIM_DIR: self.pi},
            self.env_file,
        )
        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.pattern_count, 2)  # blockedTerms + localHome は必ずある

    def test_gate_hits_planted_blocked_term(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "planted"
            root.mkdir()
            (root / "note.md").write_text("mentions ZZ-Test-Blocked-Term here\n", encoding="utf-8")
            hits = public_slim.scan_outputs({"planted": root}, ["zz-test-blocked-term"])
            self.assertEqual(hits, {"zz-test-blocked-term": ["planted/note.md"]})

    def test_gate_fails_closed_when_blocked_terms_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_env = _env_file_with_terms(Path(tmp), "")
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim.resolve_gate_patterns(REPO_ROOT, self.manifest["gate"], empty_env)
            missing_env = Path(tmp) / "missing.env"
            with self.assertRaises(public_slim.SlimBuildError):
                public_slim.resolve_gate_patterns(REPO_ROOT, self.manifest["gate"], missing_env)

    def test_builder_exit_codes_for_gate_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_env = _env_file_with_terms(Path(tmp), "")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--check", "--env-file", str(empty_env)],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
            self.assertIn(public_slim.BLOCKED_TERMS_KEY, result.stderr)
            # 生成物に必ず含まれる語をブロック語にすると gate が exit 1 で落ちる
            hit_dir = Path(tmp) / "hit"
            hit_dir.mkdir()
            hit_env = _env_file_with_terms(hit_dir, "distribute")
            result = subprocess.run(
                [sys.executable, str(BUILDER), "--check", "--env-file", str(hit_env)],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            hit_lines = [line for line in result.stdout.splitlines() if line.strip().startswith("HIT")]
            self.assertTrue(hit_lines, msg=result.stdout)
            for line in hit_lines:  # ブロック語の値は表示しない
                self.assertNotIn("distribute", line)


if __name__ == "__main__":
    unittest.main()

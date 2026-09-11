#!/usr/bin/env python3
"""distribute が guard hook の lib 依存を解決する（hookLibClosure）契約テスト。

hook は `source "$HOOK_DIR/lib/<name>.sh"` で隣の lib を静的に参照する。かつては
その推移閉包を各 target の config.json が手で列挙しており、opencode の宣言に
review-gate.sh が無く「共有ライブラリが読めません」で全 Bash が deny された
（2026-08-05）。今は `<hooks dir>/lib/` の distribute エントリに
`hookLibClosure: true` を付けると resolver が閉包を計算して配布物に含める。
ここでは (1) 閉包の計算規則、(2) 宣言の形の検証、(3) 本物の target が閉包で
配られていること、(4) 配布物で hook が実際に動くこと、を見る。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness_lib.resolver import HOOK_LIB_REF, hook_lib_closure, manifest  # noqa: E402
from tests._helpers import run_distribute_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGETS_DIR = REPO_ROOT / "packages" / "targets"

GUARD_HOOK = "packages/core/hooks/block-dangerous-in-bash.sh"


def iter_target_configs():
    for cfg_path in sorted(TARGETS_DIR.glob("*/config.json")):
        yield cfg_path.parent.name, json.loads(cfg_path.read_text(encoding="utf-8"))


def _b(text: str) -> bytes:
    return text.encode("utf-8")


class TestHookLibClosure(unittest.TestCase):
    LIBS = {
        "a.sh": _b("a() { :; }\n"),
        "b.sh": _b('source "$HOOK_DIR/lib/a.sh"\nb() { :; }\n'),
        "c.sh": _b("c() { :; }\n"),
        "unused.sh": _b("unused() { :; }\n"),
    }

    def test_direct_reference(self):
        hooks = {"h.sh": _b('source "$HOOK_DIR/lib/c.sh"\n')}
        self.assertEqual(hook_lib_closure(hooks, self.LIBS), {"c.sh"})

    def test_nested_lib_reference_is_followed(self):
        hooks = {"h.sh": _b('source "$HOOK_DIR/lib/b.sh"\n')}
        self.assertEqual(hook_lib_closure(hooks, self.LIBS), {"a.sh", "b.sh"})

    def test_guarded_soft_and_braced_references_count(self):
        hooks = {
            "h.sh": _b(
                'if [ -r "$HOOK_DIR/lib/a.sh" ]; then\n  source "$HOOK_DIR/lib/a.sh"\nfi\n'
                'source "${HOOK_DIR}/lib/c.sh" 2>/dev/null || true\n'
            )
        }
        self.assertEqual(hook_lib_closure(hooks, self.LIBS), {"a.sh", "c.sh"})

    def test_comment_lines_are_not_references(self):
        hooks = {"h.sh": _b('# source "$HOOK_DIR/lib/a.sh" は将来\nsource "$HOOK_DIR/lib/c.sh"\n')}
        self.assertEqual(hook_lib_closure(hooks, self.LIBS), {"c.sh"})

    def test_hooks_without_references_yield_empty_closure(self):
        hooks = {"h.sh": _b("echo hi\n"), "g.py": _b("print(1)\n")}
        self.assertEqual(hook_lib_closure(hooks, self.LIBS), set())

    def test_missing_lib_fails_and_names_referrer(self):
        hooks = {"h.sh": _b('source "$HOOK_DIR/lib/nope.sh"\n')}
        with self.assertRaises(ValueError) as ctx:
            hook_lib_closure(hooks, self.LIBS)
        self.assertIn("h.sh", str(ctx.exception))
        self.assertIn("lib/nope.sh", str(ctx.exception))

    def test_missing_nested_lib_names_the_lib_as_referrer(self):
        libs = dict(self.LIBS, **{"d.sh": _b('source "$HOOK_DIR/lib/nope.sh"\n')})
        hooks = {"h.sh": _b('source "$HOOK_DIR/lib/d.sh"\n')}
        with self.assertRaises(ValueError) as ctx:
            hook_lib_closure(hooks, libs)
        self.assertIn("d.sh", str(ctx.exception))

    def test_every_lib_reference_form_in_core_hooks_is_recognised(self):
        """core の hook が使う lib 参照の書き方はすべて HOOK_LIB_REF で拾える。

        `/lib/` を含む非コメント行で HOOK_DIR を使っているのに正規表現に掛からないものが
        あれば参照の書き方が増えた（閉包から漏れる）ので落とす。
        """
        hooks_dir = REPO_ROOT / "packages" / "core" / "hooks"
        unmatched = []
        for path in sorted(hooks_dir.glob("*.sh")) + sorted((hooks_dir / "lib").glob("*.sh")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#") or "/lib/" not in line:
                    continue
                if "HOOK_DIR" in line and not HOOK_LIB_REF.search(line):
                    unmatched.append(f"{path.name}:{lineno}: {line.strip()}")
        self.assertEqual(unmatched, [], msg="\n".join(unmatched))


class TestHookLibClosureManifest(unittest.TestCase):
    """hookLibClosure 宣言の形と manifest への反映（合成 repo）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        hooks = self.repo / "packages" / "core" / "hooks"
        (hooks / "lib").mkdir(parents=True)
        (hooks / "guard.sh").write_text('source "$HOOK_DIR/lib/gate.sh"\n', encoding="utf-8")
        (hooks / "plain.sh").write_text("exit 0\n", encoding="utf-8")
        (hooks / "lib" / "gate.sh").write_text('source "$HOOK_DIR/lib/norm.sh"\n', encoding="utf-8")
        (hooks / "lib" / "norm.sh").write_text("norm() { :; }\n", encoding="utf-8")
        (hooks / "lib" / "unused.sh").write_text("unused() { :; }\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _cfg(distribute: dict) -> dict:
        return {"name": "t", "distribute": distribute}

    def test_closure_is_added_and_unused_lib_is_not(self):
        files = manifest("t", self.repo, self._cfg({
            "claude-hooks/lib/": {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
            "claude-hooks/guard.sh": {"source": "packages/core/hooks/guard.sh"},
            "claude-hooks/plain.sh": {"source": "packages/core/hooks/plain.sh"},
        })).files
        self.assertEqual(
            sorted(k for k in files if k.startswith("claude-hooks/lib/")),
            ["claude-hooks/lib/gate.sh", "claude-hooks/lib/norm.sh"],
        )

    def test_declaration_order_does_not_matter(self):
        """lib/ エントリが hook エントリより前に書かれていても閉包は hook 群が出揃ってから解く。"""
        early = manifest("t", self.repo, self._cfg({
            "claude-hooks/lib/": {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
            "claude-hooks/guard.sh": {"source": "packages/core/hooks/guard.sh"},
        })).files
        late = manifest("t", self.repo, self._cfg({
            "claude-hooks/guard.sh": {"source": "packages/core/hooks/guard.sh"},
            "claude-hooks/lib/": {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
        })).files
        self.assertEqual(sorted(early), sorted(late))

    def test_flag_requires_hooks_dir_lib_directory_dest(self):
        for bad_dest in ("claude-hooks/lib/gate.sh", "lib/", "claude-hooks/libs/", "claude-hooks/lib/extra/"):
            with self.subTest(dest=bad_dest), self.assertRaises(ValueError):
                manifest("t", self.repo, self._cfg({
                    bad_dest: {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
                    "claude-hooks/guard.sh": {"source": "packages/core/hooks/guard.sh"},
                }))

    def test_flag_without_any_hook_in_parent_fails(self):
        with self.assertRaises(ValueError) as ctx:
            manifest("t", self.repo, self._cfg({
                "claude-hooks/lib/": {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
            }))
        self.assertIn("claude-hooks/", str(ctx.exception))

    def test_missing_referenced_lib_fails_with_target_context(self):
        (self.repo / "packages" / "core" / "hooks" / "lib" / "norm.sh").unlink()
        with self.assertRaises(ValueError) as ctx:
            manifest("t", self.repo, self._cfg({
                "claude-hooks/lib/": {"source": "packages/core/hooks/lib/", "hookLibClosure": True},
                "claude-hooks/guard.sh": {"source": "packages/core/hooks/guard.sh"},
            }))
        self.assertIn("lib/norm.sh", str(ctx.exception))
        self.assertIn("claude-hooks/lib/", str(ctx.exception))


class TestRealTargetsUseClosure(unittest.TestCase):
    def test_no_hand_written_lib_entries_remain(self):
        """hook をファイル単位で配る target は lib を手で列挙せず hookLibClosure で解く。"""
        offenders = []
        for target, cfg in iter_target_configs():
            for dest, spec in cfg.get("distribute", {}).items():
                source = spec.get("source") if isinstance(spec, dict) else None
                if (
                    isinstance(source, str)
                    and source.startswith("packages/core/hooks/lib/")
                    and source.endswith(".sh")
                ):
                    offenders.append(f"{target}: {dest}")
        self.assertEqual(offenders, [], msg="\n".join(offenders))

    def test_every_hard_referenced_lib_is_in_the_manifest(self):
        """2026-08-05 の配布漏れ再発防止: 配布された hook が参照する lib は同じ manifest にある。"""
        failures = []
        for target, cfg in iter_target_configs():
            distribute = cfg.get("distribute", {})
            lib_dests = [
                d for d, s in distribute.items() if isinstance(s, dict) and s.get("hookLibClosure")
            ]
            if not lib_dests:
                continue
            files = manifest(target, REPO_ROOT, cfg).files
            for lib_dest in lib_dests:
                parent = lib_dest.rstrip("/").rsplit("/", 1)[0] + "/"
                for rel, data in files.items():
                    if not rel.startswith(parent) or "/" in rel[len(parent):]:
                        continue
                    for line in data.decode("utf-8", errors="replace").splitlines():
                        if line.lstrip().startswith("#"):
                            continue
                        for lib_name in HOOK_LIB_REF.findall(line):
                            if lib_dest + lib_name not in files:
                                failures.append(
                                    f"{target}: {rel} → {lib_dest}{lib_name} が manifest に無い"
                                )
        self.assertEqual(failures, [], msg="\n".join(failures))


class TestDistributedGuardHookSmoke(unittest.TestCase):
    """配布宣言どおりに組んだ live ツリーで guard hook を実際に実行する。

    静的な閉包計算が参照の書き方を読み漏らしても、ここで露見する。distribute
    --push --live で fixture へ実配布し、配布された block-dangerous-in-bash.sh を
    hook protocol（stdin JSON）で起動して「無害コマンド = allow (exit 0) /
    危険コマンド = deny (exit 2)」を検証する。依存（lib/・policy table・jq・perl）
    がひとつでも欠ければ fail-closed の exit 2 になり、無害コマンドの allow 検証が落ちる。
    """

    @staticmethod
    def _guard_hook_targets():
        """block-dangerous-in-bash.sh をファイル単位で配るターゲットと配布先を列挙する。"""
        for target, cfg in iter_target_configs():
            for dest, spec in cfg.get("distribute", {}).items():
                source = spec.get("source") if isinstance(spec, dict) else None
                if source == GUARD_HOOK:
                    yield target, dest

    def _run_hook(self, hook: Path, command: str, runtime: str) -> subprocess.CompletedProcess:
        payload = json.dumps({"tool_input": {"command": command}})
        env = {**os.environ, "HARNESS_RUNTIME": runtime}
        return subprocess.run(
            ["bash", str(hook)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(hook.parent),
            env=env,
        )

    def test_distributed_guard_hook_allows_benign_and_denies_dangerous(self):
        targets = list(self._guard_hook_targets())
        self.assertTrue(targets, msg="guard hook を配るターゲットが見つからない")
        for target, dest in targets:
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as tmp:
                    live = Path(tmp) / "live"
                    live.mkdir()
                    exit_code, output = run_distribute_cli(
                        [target, "--push", "--live", str(live)]
                    )
                    self.assertEqual(exit_code, 0, msg=output)
                    hook = live / dest
                    self.assertTrue(hook.is_file(), msg=f"{dest} が配布されていない")

                    benign = self._run_hook(hook, "echo hi", target)
                    self.assertEqual(
                        benign.returncode, 0,
                        msg=f"無害コマンドが allow されない（配布物の依存欠落の疑い）: {benign.stderr}",
                    )

                    # gh-repo-delete-edit は全 hook runtime（claude/opencode/omp/pi）で
                    # 実効 action=block（gh-pr-merge-close は opencode では confirm で
                    # native ask 所有になり hook 経路から外れるため、ここでは使わない）
                    dangerous = self._run_hook(hook, "gh repo delete owner/repo", target)
                    self.assertEqual(
                        dangerous.returncode, 2,
                        msg=f"危険コマンドが deny されない: stdout={dangerous.stdout} stderr={dangerous.stderr}",
                    )


if __name__ == "__main__":
    unittest.main()

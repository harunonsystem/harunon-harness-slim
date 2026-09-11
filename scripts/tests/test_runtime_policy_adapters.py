#!/usr/bin/env python3
"""Runtime native adapters が同じ Policy Kernel 判定を強制することを検証する。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PI_ADAPTER = REPO_ROOT / "packages/core/pi-extensions/harness-policy.js"
OPENCODE_ADAPTER = REPO_ROOT / "packages/core/opencode-plugins/harness-policy.js"
DISTRIBUTE = REPO_ROOT / "scripts/distribute.py"


def run_node(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )


def start_task_with_progress(repo: Path, task_id: str) -> None:
    """repo で Core Workflow を開始し、1 event 進めて「進行中」にする。

    task.start 直後（intake, revision 0）は kernel が WORKFLOW_INACTIVE として gate
    しないため、「別タスク進行中」の fixture には progress が必要。isolate は
    pr.create の allowedStates に含まれず WORKFLOW_NOT_READY になる。
    """
    harnessctl = REPO_ROOT / "packages/core/policy/harnessctl.py"
    for request in (
        {"type": "task.start", "taskId": task_id},
        {"type": "phase.advance", "event": "requirements_clear", "expectedRevision": 0},
    ):
        result = subprocess.run(
            [sys.executable, str(harnessctl), "apply"],
            input=json.dumps(request),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestPiFamilyAdapter(unittest.TestCase):
    def test_pi_and_omp_handler_fail_closed_on_kernel_rejection(self) -> None:
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler(async (action, cwd, command) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} command=${{command}} not ready`}}
          ));
          const result = await handler(
            {{input: {{command: 'rtk gh pr create --fill'}}}},
            {{cwd: '/tmp/target'}},
          );
          console.log(JSON.stringify(result));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "block": True,
                "reason": (
                    "Core Workflow policy blocked pr.create: pr.create at /tmp/target "
                    "command=rtk gh pr create --fill not ready"
                ),
            },
        )

    def test_pi_and_omp_handler_uses_ctx_cwd_not_dead_event_fields(self) -> None:
        """P1-B 再発ガード: event.cwd / event.directory は pi/omp では常に undefined。

        handler は (event, ctx) を受け取り ctx.cwd だけを base として使う。event 側に
        cwd/directory を紛れ込ませても無視されることを確認する。
        """
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler(async (action, cwd) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} not ready`}}
          ));
          const result = await handler(
            {{
              cwd: '/decoy/from-event-cwd',
              directory: '/decoy/from-event-directory',
              input: {{command: 'rtk gh pr create --fill'}},
            }},
            {{cwd: '/tmp/target'}},
          );
          console.log(JSON.stringify(result));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "block": True,
                "reason": "Core Workflow policy blocked pr.create: pr.create at /tmp/target not ready",
            },
        )

    def test_pi_and_omp_handler_allows_when_workflow_not_started(self) -> None:
        """Core Workflow 未開始（STATE_NOT_FOUND）は素通し（Claude hook と同じ段階導入）。"""
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler(async () => (
            {{code: 2, reason: JSON.stringify({{code: 'STATE_NOT_FOUND', path: '/x/state.json'}})}}
          ));
          const result = await handler(
            {{input: {{command: 'rtk gh pr create --fill'}}}},
            {{cwd: '/tmp/target'}},
          );
          console.log(JSON.stringify(result === undefined));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")

    def test_pi_and_omp_handler_allows_when_workflow_inactive(self) -> None:
        """complete 済み / 着手前放置の state（WORKFLOW_INACTIVE）も未開始と同じく素通し。"""
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler(async () => (
            {{code: 2, reason: JSON.stringify({{code: 'WORKFLOW_INACTIVE', phase: 'complete', revision: 9}})}}
          ));
          const result = await handler(
            {{input: {{command: 'rtk gh pr create --fill'}}}},
            {{cwd: '/tmp/target'}},
          );
          console.log(JSON.stringify(result === undefined));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")

    def test_pi_and_omp_distribute_the_same_adapter(self) -> None:
        for target in ("pi", "omp"):
            with self.subTest(target=target):
                result = subprocess.run(
                    [sys.executable, str(DISTRIBUTE), target, "--list"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("extensions/harness-policy.js", result.stdout)


class TestOpenCodeAdapter(unittest.TestCase):
    def test_opencode_hook_uses_directory_directly_and_forwards_command(self) -> None:
        """directoryFromTool は削除済み。base は directory をそのまま使い、CMD 内の

        `cd /tmp` はもう解決されない（kernel 側の repo_target 解決に一本化された）。
        payload に command が forward されることも合わせて確認する。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async (action, cwd, command) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} command=${{command}} not ready`}}
          ));
          const hooks = await plugin({{directory: process.cwd()}});
          try {{
            await hooks['tool.execute.before'](
              {{tool: 'bash'}},
              {{args: {{command: 'cd /tmp && rtk gh pr create --fill'}}}},
            );
          }} catch (error) {{
            console.log(error.message);
          }}
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            (
                f"Core Workflow policy blocked pr.create: pr.create at {REPO_ROOT} "
                "command=cd /tmp && rtk gh pr create --fill not ready"
            ),
        )

    def test_directory_from_tool_export_is_removed(self) -> None:
        """再発ガード: CMD の cd 抽出（directoryFromTool）は opencode adapter から消えている。"""
        source = f"""
          import * as adapter from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          console.log(JSON.stringify('directoryFromTool' in adapter));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "false")

    def test_opencode_hook_allows_when_workflow_not_started(self) -> None:
        """Core Workflow 未開始（STATE_NOT_FOUND）は素通し（Claude hook と同じ段階導入）。"""
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async () => (
            {{code: 2, reason: JSON.stringify({{code: 'STATE_NOT_FOUND', path: '/x/state.json'}})}}
          ));
          const hooks = await plugin({{directory: process.cwd()}});
          await hooks['tool.execute.before'](
            {{tool: 'bash'}},
            {{args: {{command: 'rtk gh pr create --fill'}}}},
          );
          console.log('allowed');
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "allowed")

    def test_opencode_hook_allows_when_workflow_inactive(self) -> None:
        """complete 済み / 着手前放置の state（WORKFLOW_INACTIVE）も未開始と同じく素通し。

        OpenCode は rigor casual による skip を持たないため、旧タスクの state が残った
        checkout では毎回 `Core Workflow policy blocked pr.create` が出ていた（2026-08-26）。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async () => (
            {{code: 2, reason: JSON.stringify({{code: 'WORKFLOW_INACTIVE', phase: 'complete', revision: 9}})}}
          ));
          const hooks = await plugin({{directory: process.cwd()}});
          await hooks['tool.execute.before'](
            {{tool: 'bash'}},
            {{args: {{command: 'rtk gh pr create --fill'}}}},
          );
          console.log('allowed');
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "allowed")

    def test_opencode_hook_prefers_worktree_over_directory(self) -> None:
        """issue #80 再発ガード: plugin context に worktree があれば directory ではなく

        worktree を authorize の cwd に使う（harness-workflow.js と同じ
        `worktree ?? directory`）。directory が親リポジトリを指しても、親の
        Core Workflow 状態で今回の PR 作成が判定されない。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async (action, cwd) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} not ready`}}
          ));
          const hooks = await plugin({{
            directory: '/parent/repo',
            worktree: '/parent/repo/.worktrees/feature',
          }});
          try {{
            await hooks['tool.execute.before'](
              {{tool: 'bash'}},
              {{args: {{command: 'rtk gh pr create --fill'}}}},
            );
          }} catch (error) {{
            console.log(error.message);
          }}
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            (
                "Core Workflow policy blocked pr.create: pr.create at "
                "/parent/repo/.worktrees/feature not ready"
            ),
        )

    def test_opencode_hook_falls_back_to_directory_when_worktree_is_root(self) -> None:
        """codex P2 再発ガード: non-git セッションでは OpenCode が worktree に "/" を

        渡す（opencode 本体も `worktree !== "/" ? worktree : directory` で防御して
        いる）。"/" を base にすると相対 cd の解決が壊れるため directory へ
        フォールバックする。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async (action, cwd) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} not ready`}}
          ));
          const hooks = await plugin({{directory: '/home/me/projects', worktree: '/'}});
          try {{
            await hooks['tool.execute.before'](
              {{tool: 'bash'}},
              {{args: {{command: 'rtk gh pr create --fill'}}}},
            );
          }} catch (error) {{
            console.log(error.message);
          }}
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Core Workflow policy blocked pr.create: pr.create at /home/me/projects not ready",
        )

    def test_opencode_hook_uses_bash_tool_cwd_argument_over_session_context(self) -> None:
        """2026-08-26 再発ガード: OpenCode の bash tool は `cwd` 引数で独立 worktree を

        指せる。context.worktree はセッション起点のままなので、cwd 引数を無視すると
        親リポジトリの Core Workflow state（別タスク）で pr.create が判定される。
        絶対パスはそのまま、相対パスはセッション base 基準で解決する。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy(async (action, cwd) => (
            {{code: 2, reason: `${{action}} at ${{cwd}} not ready`}}
          ));
          const hooks = await plugin({{directory: '/parent/repo', worktree: '/parent/repo'}});
          for (const cwd of ['/elsewhere/worktrees/feature', '../worktrees/feature']) {{
            try {{
              await hooks['tool.execute.before'](
                {{tool: 'bash'}},
                {{args: {{command: 'rtk gh pr create --fill', cwd}}}},
              );
            }} catch (error) {{
              console.log(error.message);
            }}
          }}
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "Core Workflow policy blocked pr.create: pr.create at "
                "/elsewhere/worktrees/feature not ready",
                "Core Workflow policy blocked pr.create: pr.create at "
                "/parent/worktrees/feature not ready",
            ],
        )

    def test_opencode_classifies_github_mcp_publish_tools(self) -> None:
        source = f"""
          import {{ actionFromTool }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          console.log(JSON.stringify([
            actionFromTool({{tool: 'mcp__github__create_pull_request'}}, {{}}),
            actionFromTool({{tool: 'mcp__github__merge_pull_request'}}, {{}}),
          ]));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(json.loads(result.stdout), ["pr.create", "pr.merge"])


class TestRealKernelCrossRepoResolution(unittest.TestCase):
    """B-4 結合テスト: pi adapter が実 kernel を叩き、CMD の `cd` 越境が

    ctx.cwd の repo ではなく対象 repo の state で判定されることを確認する。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo_a = self.root / "repo-a"
        self.repo_b = self.root / "repo-b"
        for repo in (self.repo_a, self.repo_b):
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                check=True,
            )
            (repo / "README.md").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cd_in_command_authorizes_against_target_repo_state_not_ctx_cwd(self) -> None:
        # repo-b だけ Core Workflow を進行中にする（isolate なので pr.create は
        # WORKFLOW_NOT_READY になる）。
        start_task_with_progress(self.repo_b, "HAR-B4")

        command = f"cd {self.repo_b} && gh pr create --fill"
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler();
          const result = await handler(
            {{input: {{command: {json.dumps(command)}}}}},
            {{cwd: {json.dumps(str(self.repo_a))}}},
          );
          console.log(JSON.stringify(result));
        """
        result = run_node(source)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        # repo-a には state が無い（STATE_NOT_FOUND）ので、もし ctx.cwd(repo-a) で
        # 判定されていたら素通り(undefined)になる。repo-b の state で判定された
        # 結果としてブロックされることが、command 越境解決の証拠になる。
        self.assertIsNotNone(payload)
        self.assertTrue(payload["block"], msg=payload)
        self.assertIn("WORKFLOW_NOT_READY", payload["reason"])


class TestRealKernelWorktreeResolution(unittest.TestCase):
    """issue #80 結合テスト: 親リポジトリで別タスクが進行中でも、独立 worktree の

    PR 作成は worktree 自身の Core Workflow 状態（未開始なら STATE_NOT_FOUND →
    素通し）で判定される。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.repo / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "initial"], check=True)
        # 親リポジトリだけ Core Workflow を進行中にする（isolate なので
        # 親の state で判定されると pr.create は WORKFLOW_NOT_READY になる）。
        start_task_with_progress(self.repo, "HAR-80")
        self.worktree = self.root / "wt-feature"
        subprocess.run(
            [
                "git", "-C", str(self.repo), "worktree", "add", "-q",
                "-b", "feature/wt", str(self.worktree),
            ],
            check=True,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_opencode_authorizes_against_worktree_state_not_parent_directory(self) -> None:
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy();
          const hooks = await plugin({{
            directory: {json.dumps(str(self.repo))},
            worktree: {json.dumps(str(self.worktree))},
          }});
          await hooks['tool.execute.before'](
            {{tool: 'bash'}},
            {{args: {{command: 'gh pr create --fill'}}}},
          );
          console.log('allowed');
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # worktree の state は未開始（STATE_NOT_FOUND）なので素通し。親の
        # intake state で判定されていたら WORKFLOW_NOT_READY で throw する。
        self.assertEqual(result.stdout.strip(), "allowed")

    def test_opencode_bash_cwd_argument_authorizes_against_that_worktree_state(self) -> None:
        """セッションは親リポジトリで起動（directory = worktree = 親）、bash tool の

        cwd 引数だけが独立 worktree を指す形（gwm で切った worktree で作業する
        OpenCode の実運用）。worktree 自身の state（未開始）で判定され素通しになる。
        """
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy();
          const hooks = await plugin({{
            directory: {json.dumps(str(self.repo))},
            worktree: {json.dumps(str(self.repo))},
          }});
          await hooks['tool.execute.before'](
            {{tool: 'bash'}},
            {{args: {{command: 'gh pr create --fill', cwd: {json.dumps(str(self.worktree))}}}}},
          );
          console.log('allowed');
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "allowed")

    def test_opencode_without_worktree_still_authorizes_against_directory(self) -> None:
        """non-worktree 環境の既存挙動維持: worktree が無ければ directory で判定する。"""
        source = f"""
          import {{ createHarnessPolicy }} from {json.dumps(OPENCODE_ADAPTER.as_uri())};
          const plugin = createHarnessPolicy();
          const hooks = await plugin({{directory: {json.dumps(str(self.repo))}}});
          try {{
            await hooks['tool.execute.before'](
              {{tool: 'bash'}},
              {{args: {{command: 'gh pr create --fill'}}}},
            );
            console.log('allowed');
          }} catch (error) {{
            console.log(error.message);
          }}
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("WORKFLOW_NOT_READY", result.stdout.strip())

    def test_pi_ctx_cwd_in_worktree_authorizes_against_worktree_state(self) -> None:
        """pi/omp は ctx.cwd がそのまま worktree を指す（directory/worktree の分離が

        存在しない）。worktree 内で起動したセッションが親の state に影響されない
        ことを実 kernel で固定する。
        """
        source = f"""
          import {{ createHarnessPolicyHandler }} from {json.dumps(PI_ADAPTER.as_uri())};
          const handler = createHarnessPolicyHandler();
          const result = await handler(
            {{input: {{command: 'gh pr create --fill'}}}},
            {{cwd: {json.dumps(str(self.worktree))}}},
          );
          console.log(JSON.stringify(result === undefined));
        """
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")


if __name__ == "__main__":
    unittest.main()

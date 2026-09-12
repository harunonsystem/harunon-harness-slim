// claude-hooks-bridge
//
// Claude Code hooks (packages/core/hooks/*.sh) を OpenCode 上で無改修実行する adapter。
// bash の tool.execute.before を Claude の Bash / tool_input に写して hookRunner
// （../hook-runner/hook-runner.js）へ渡し、decision を throw（deny）/ args 書き戻し
// （rewrite）に写す。どの hook をどの順で流すか・wire protocol・required hook の
// fail-closed は hookRunner が policy/hook-pipeline.json から決める（この file に
// hook 一覧は無い）。
//
// OpenCode 固有の差（ホスト能力差。scripts/tests/fixtures/hook-protocol.json に divergence
// として宣言）: tool.execute.before で throw する以外に確認を求める経路が無いため、
// ask は deny として扱う。
//
// 配布レイアウト: runtime/harunon-opencode/claude-hooks-bridge.js（自ファイル）の隣に
// runtime/hook-runner/・runtime/claude-hooks/・runtime/policy/ が配布される
// （opencode config.json の distribute 宣言）。~/.claude/hooks への実行時依存は持たない —
// claude target 未配布のマシンで guard が黙って無効化される穴だった。

import { createHookRunner } from "../hook-runner/hook-runner.js";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";

export const ClaudeHooksBridge = async ({ directory, worktree, hooksDir, tablePath } = {}) => {
  const runner = createHookRunner({ runtime: "opencode", hooksDir, tablePath });
  const base = sessionBaseCwd({ directory, worktree });

  return {
    "tool.execute.before": async (input, output) => {
      if (input?.tool !== "bash") return;
      if (!output?.args || typeof output.args.command !== "string") return;
      // hook は spawn cwd で git rev-parse を打つ。bash tool の cwd 引数を無視すると
      // worktree 側で発行した push 承認フラグが親リポジトリの KEY で探され見つからない。
      const cwd = resolveToolCwd(base, output.args.cwd);
      const result = await runner.preToolUse("Bash", { command: output.args.command }, cwd);
      for (const warning of result.warnings) {
        console.warn(`[claude-hooks-bridge] ${warning}`);
      }
      if (result.decision !== "allow") {
        throw new Error(result.reason);
      }
      Object.assign(output.args, result.finalInput);
    },
  };
};

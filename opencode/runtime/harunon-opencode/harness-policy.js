import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";

const KERNEL = fileURLToPath(new URL("../policy/harnessctl.py", import.meta.url));

export function actionFromTool(input, output) {
  const tool = input?.tool ?? "";
  if (/github.*create.*pull.*request/i.test(tool)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(tool)) return "pr.merge";
  if (tool !== "bash") return undefined;
  const command = output?.args?.command;
  if (typeof command !== "string") return undefined;
  if (/(^|[;&|\n]\s*)(rtk\s+)?gh\s+pr\s+create(?:\s|$)/.test(command)) {
    return "pr.create";
  }
  if (/(^|[;&|\n]\s*)(rtk\s+)?gh\s+pr\s+merge(?:\s|$)/.test(command)) {
    return "pr.merge";
  }
  return undefined;
}

function runAuthorize(action, cwd, command) {
  return new Promise((resolve) => {
    const child = spawn("python3", [KERNEL, "authorize"], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", (error) => resolve({ code: 3, reason: error.message }));
    child.on("close", (code) => resolve({
      code: code ?? 3,
      reason: stdout.trim() || stderr.trim(),
    }));
    child.stdin.end(JSON.stringify({ repo: cwd, action, command }));
  });
}

// 進行中の Core Workflow タスクが無いリポジトリは gate を課さない（Claude hook と同じ段階導入）。
// 未開始（STATE_NOT_FOUND）だけでなく、complete 済み / 着手前で放置された state
// （WORKFLOW_INACTIVE）も含める。kernel の task_is_active が判定の SSOT。
const UNGATED_KERNEL_CODES = new Set(["STATE_NOT_FOUND", "WORKFLOW_INACTIVE"]);

export function isWorkflowInactive(reason) {
  try {
    return UNGATED_KERNEL_CODES.has(JSON.parse(reason)?.code);
  } catch {
    return false;
  }
}

export function createHarnessPolicy(authorize = runAuthorize) {
  // directory は project root を指すため、独立 worktree では別タスクの state を
  // 参照してしまう。worktree を優先し、さらに bash tool の cwd 引数（セッションと
  // 別の worktree でコマンドを実行する形）があればそれを base にする
  // （harness-workflow.js と同じ解決。tool-cwd.js が SSOT）。
  return async ({ directory, worktree }) => ({
    "tool.execute.before": async (input, output) => {
      const action = actionFromTool(input, output);
      if (action === undefined) return;
      const command = output?.args?.command;
      const cwd = resolveToolCwd(sessionBaseCwd({ directory, worktree }), output?.args?.cwd);
      const result = await authorize(action, cwd, command);
      if (result.code !== 0 && !isWorkflowInactive(result.reason)) {
        throw new Error(`Core Workflow policy blocked ${action}: ${result.reason}`);
      }
    },
  });
}

export const HarnessPolicy = createHarnessPolicy();

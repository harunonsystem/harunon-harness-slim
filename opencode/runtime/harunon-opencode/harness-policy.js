import { fileURLToPath } from "node:url";
import { runProcess } from "../hook-runner/hook-runner.js";
import {
  AMBIGUOUS_PR_ACTION,
  classifyPrCommand,
} from "../policy/pr-action.js";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";

const KERNEL = fileURLToPath(new URL("../policy/harnessctl.py", import.meta.url));

function commandFromTool(output) {
  const args = output?.args;
  if (typeof args?.command === "string") return args.command;
  if (typeof args?.cmd === "string") return args.cmd;
  return undefined;
}

function classifyTool(input, output) {
  const tool = input?.tool ?? input?.name ?? input?.toolName ?? "";
  if (/github.*create.*pull.*request/i.test(tool)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(tool)) return "pr.merge";
  if (tool !== "bash" && tool !== "exec_command" && tool !== "interactive_shell") {
    return undefined;
  }
  return classifyPrCommand(commandFromTool(output));
}

export function actionFromTool(input, output) {
  const action = classifyTool(input, output);
  return action === AMBIGUOUS_PR_ACTION ? undefined : action;
}

async function runAuthorize(action, cwd, command) {
  const result = await runProcess("python3", [KERNEL, "authorize"], {
    cwd,
    stdin: JSON.stringify({ repo: cwd, action, command }),
  });
  return {
    code: result.code,
    reason:
      result.stdout.trim() ||
      result.stderr.trim() ||
      `harnessctl exited ${result.code}`,
  };
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
      const classification = classifyTool(input, output);
      if (classification === AMBIGUOUS_PR_ACTION) {
        throw new Error(
          "Core Workflow policy blocked ambiguous PR actions: command contains multiple PR actions",
        );
      }
      if (classification === undefined) return;
      const action = classification;
      const command = commandFromTool(output);
      const cwd = resolveToolCwd(
        sessionBaseCwd({ directory, worktree }),
        output?.args?.workdir ?? output?.args?.cwd,
      );
      const result = await authorize(action, cwd, command);
      if (result.code !== 0 && !isWorkflowInactive(result.reason)) {
        throw new Error(`Core Workflow policy blocked ${action}: ${result.reason}`);
      }
    },
  });
}

export const HarnessPolicy = createHarnessPolicy();

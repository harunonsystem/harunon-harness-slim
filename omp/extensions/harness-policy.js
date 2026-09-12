import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const DEFAULT_KERNEL = fileURLToPath(
  new URL("../policy/harnessctl.py", import.meta.url),
);

function commandFromToolCall(event) {
  return event?.input?.command ?? event?.args?.command ?? event?.params?.command;
}

export function actionFromToolCall(event) {
  const tool = event?.tool ?? event?.name ?? "";
  if (/github.*create.*pull.*request/i.test(tool)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(tool)) return "pr.merge";
  const command = commandFromToolCall(event);
  if (typeof command !== "string") return undefined;
  if (/(^|[;&|\n]\s*)(rtk\s+)?gh\s+pr\s+create(?:\s|$)/.test(command)) {
    return "pr.create";
  }
  if (/(^|[;&|\n]\s*)(rtk\s+)?gh\s+pr\s+merge(?:\s|$)/.test(command)) {
    return "pr.merge";
  }
  return undefined;
}

export function runHarnessAuthorize(action, cwd, command, kernel = DEFAULT_KERNEL) {
  return new Promise((resolve) => {
    const child = spawn("python3", [kernel, "authorize"], {
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

export function createHarnessPolicyHandler(authorize = runHarnessAuthorize) {
  return async (event, ctx) => {
    const action = actionFromToolCall(event);
    if (action === undefined) return undefined;
    const cwd = ctx?.cwd;
    const command = commandFromToolCall(event);
    const result = await authorize(action, cwd, command);
    if (result.code === 0) return undefined;
    if (isWorkflowInactive(result.reason)) return undefined;
    return {
      block: true,
      reason: `Core Workflow policy blocked ${action}: ${result.reason}`,
    };
  };
}

export default function harnessPolicy(pi) {
  pi.on("tool_call", createHarnessPolicyHandler());
}

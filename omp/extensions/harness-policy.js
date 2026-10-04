import { resolve as resolvePath } from "node:path";
import { fileURLToPath } from "node:url";
import { runProcess } from "../hook-runner/hook-runner.js";
import {
  AMBIGUOUS_PR_ACTION,
  classifyPrCommand,
} from "../policy/pr-action.js";

const DEFAULT_KERNEL = fileURLToPath(
  new URL("../policy/harnessctl.py", import.meta.url),
);

function commandFromToolCall(event) {
  const input = event?.input;
  if (typeof input?.command === "string") return input.command;
  if (typeof input?.cmd === "string") return input.cmd;
  const args = event?.args;
  if (typeof args?.command === "string") return args.command;
  if (typeof args?.cmd === "string") return args.cmd;
  const params = event?.params;
  if (typeof params?.command === "string") return params.command;
  if (typeof params?.cmd === "string") return params.cmd;
  return undefined;
}

function commandCwd(event, baseCwd) {
  const input = event?.input;
  const toolCwd =
    typeof input?.workdir === "string"
      ? input.workdir
      : typeof input?.cwd === "string"
        ? input.cwd
        : undefined;
  if (typeof toolCwd !== "string" || toolCwd.trim() === "") return baseCwd;
  return resolvePath(baseCwd || process.cwd(), toolCwd);
}

function classifyToolCall(event) {
  const tool = event?.tool ?? event?.name ?? event?.toolName ?? "";
  if (/github.*create.*pull.*request/i.test(tool)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(tool)) return "pr.merge";
  return classifyPrCommand(commandFromToolCall(event));
}

export function actionFromToolCall(event) {
  const action = classifyToolCall(event);
  return action === AMBIGUOUS_PR_ACTION ? undefined : action;
}

export async function runHarnessAuthorize(action, cwd, command, kernel = DEFAULT_KERNEL) {
  const result = await runProcess("python3", [kernel, "authorize"], {
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

export function createHarnessPolicyHandler(authorize = runHarnessAuthorize) {
  return async (event, ctx) => {
    const classification = classifyToolCall(event);
    if (classification === AMBIGUOUS_PR_ACTION) {
      return {
        block: true,
        reason:
          "Core Workflow policy blocked ambiguous PR actions: command contains multiple PR actions",
      };
    }
    if (classification === undefined) return undefined;
    const action = classification;
    const cwd = commandCwd(event, ctx?.cwd);
    const command = commandFromToolCall(event);
    const result = await authorize(action, cwd, command);
    if (result.code === 0) return undefined;
    return {
      block: true,
      reason: `Core Workflow policy blocked ${action}: ${result.reason}`,
    };
  };
}

export default function harnessPolicy(pi) {
  pi.on("tool_call", createHarnessPolicyHandler());
}

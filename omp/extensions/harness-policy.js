import { resolve as resolvePath } from "node:path";
import { AMBIGUOUS_PR_ACTION } from "../policy/pr-action.js";
import { authorize, classifyToolCall, gateToolCall } from "../policy/publication-gate.js";

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

const toolNameOf = (event) => event?.tool ?? event?.name ?? event?.toolName ?? "";

export function actionFromToolCall(event) {
  const action = classifyToolCall(toolNameOf(event), commandFromToolCall(event));
  return action === AMBIGUOUS_PR_ACTION ? undefined : action;
}

export function createHarnessPolicyHandler(run = authorize) {
  return async (event, ctx) => {
    const verdict = await gateToolCall(
      { toolName: toolNameOf(event), command: commandFromToolCall(event), cwd: commandCwd(event, ctx?.cwd) },
      run,
    );
    return verdict && !verdict.allowed ? { block: true, reason: verdict.reason } : undefined;
  };
}

export default function harnessPolicy(pi) {
  pi.on("tool_call", createHarnessPolicyHandler());
}

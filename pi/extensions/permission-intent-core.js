/** Shared semantic permission layer for pi and omp tool_call events. */
import { resolveCwd, settleDecision } from "../hook-runner/runtime-mapping.js";
import { loadPermissionIntent } from "../policy/permission-intent.js";
import { evaluateRuntimePermission } from "../policy/permission-runtime.js";

export function createPermissionIntentHandler(runtime, intent = loadPermissionIntent()) {
  return async (event, ctx) => {
    const project = typeof ctx?.cwd === "string" && ctx.cwd ? ctx.cwd : process.cwd();
    const cwd = resolveCwd(event?.input, project);
    const result = evaluateRuntimePermission(runtime, event, { cwd, project }, { intent, hasUI: ctx?.hasUI });
    if (!result || result.effect === "allow") return undefined;
    return settleDecision({ decision: result.effect, reason: result.reason, warnings: [] }, ctx);
  };
}

export function piPermissionIntent(pi) {
  pi.on("tool_call", createPermissionIntentHandler("pi"));
}

export function ompPermissionIntent(pi) {
  pi.on("tool_call", createPermissionIntentHandler("omp"));
}

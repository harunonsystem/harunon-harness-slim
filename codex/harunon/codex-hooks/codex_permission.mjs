/** Separate Codex PreToolUse guard; ask is left to native approval. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { decidePermission, loadPermissionIntent } from "../policy/permission-intent.js";
import { evaluateRuntimePermission } from "../policy/permission-runtime.js";
import { resolveCwd } from "../hook-runner/runtime-mapping.js";

const PATCH_TARGET = /^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$/gm;
const deny = (reason) => ({ hookSpecificOutput: {
  hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: reason,
} });

try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  const project = typeof event.cwd === "string" && event.cwd ? event.cwd : process.cwd();
  const input = event.tool_input ?? {};
  const cwd = resolve(project, resolveCwd(input, project));
  const intent = loadPermissionIntent();
  const tool = String(event.tool_name ?? event.tool ?? "").toLowerCase();
  let result;
  if (tool === "apply_patch") {
    const patch = input.patch ?? input.input ?? "";
    const resources = typeof patch === "string" ? [...patch.matchAll(PATCH_TARGET)].map((match) => match[1].trim()) : [];
    const verdict = decidePermission(intent, { action: "edit", resources, cwd, project });
    result = verdict.effect === "deny" || verdict.effect === "unresolved" ?
      { effect: "deny", reason: verdict.reason } : undefined;
  } else {
    result = evaluateRuntimePermission("codex", event, { cwd, project }, { intent });
  }
  if (result?.effect === "deny") {
    process.stdout.write(`${JSON.stringify(deny(`permission intent requires ${result.effect}: ${result.reason}`))}\n`);
  }
} catch (error) {
  process.stdout.write(`${JSON.stringify(deny(`permission intent unavailable: ${error instanceof Error ? error.message : String(error)}`))}\n`);
}

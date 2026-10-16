/** Claude PreToolUse entry for the shared permission intent. */
import { lstatSync, readFileSync } from "node:fs";
import { basename, dirname, isAbsolute, resolve, sep } from "node:path";
import { loadPermissionIntent } from "./permission-intent.js";
import { evaluateRuntimePermission } from "./permission-runtime.js";

function currentScratchpad(event) {
  // Only runtime-owned common fields establish the boundary; tool_input is model-controlled.
  const root = event.scratchpad_dir;
  const session = event.session_id;
  if (event.hook_event_name !== "PreToolUse" || !["Read", "Edit", "Write"].includes(event.tool_name) ||
      typeof root !== "string" || !isAbsolute(root) || root.includes("\0") ||
      root.split(sep).some((part) => part === "." || part === "..") ||
      typeof session !== "string" || !session || session === "." || session === ".." || session.includes(sep)) return undefined;
  const directory = resolve(root);
  if (basename(directory) !== "scratchpad" || basename(dirname(directory)) !== session) return undefined;
  const file = event.tool_input?.file_path;
  // Lexically removing '..' before resolving symlinks could hide an escape.
  if (typeof file !== "string" || file.includes("\0") || file.split(sep).includes("..")) return undefined;
  try {
    return lstatSync(directory).isDirectory() && lstatSync(dirname(directory)).isDirectory() ? directory : undefined;
  } catch {
    return undefined; // An unavailable session directory keeps the original permission decision.
  }
}

try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  const cwd = event.cwd || process.cwd();
  const options = { intent: loadPermissionIntent() };
  let result = evaluateRuntimePermission("claude", event, { cwd, project: cwd }, options);
  if (result?.effect === "ask") {
    const scratchpad = currentScratchpad(event);
    if (scratchpad && evaluateRuntimePermission("claude", event, { cwd, project: scratchpad }, options)?.effect === "allow") {
      // Silence preserves Claude's native rules; emitting allow would override them.
      result = undefined;
    }
  }
  if (result) {
    process.stdout.write(`${JSON.stringify({ hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: result.effect,
      permissionDecisionReason: result.reason,
    } })}\n`);
  }
} catch (error) {
  process.stderr.write(`permission intent unavailable: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 2;
}

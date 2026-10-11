/** Claude PreToolUse entry for the shared permission intent. */
import { readFileSync } from "node:fs";
import { evaluateRuntimePermission } from "./permission-runtime.js";

try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  const cwd = event.cwd || process.cwd();
  const result = evaluateRuntimePermission("claude", event, { cwd, project: cwd });
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

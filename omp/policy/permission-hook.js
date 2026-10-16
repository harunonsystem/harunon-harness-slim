/** Claude PreToolUse entry for the shared permission intent. */
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, resolve, sep } from "node:path";
import { loadPermissionIntent } from "./permission-intent.js";
import { evaluateRuntimePermission } from "./permission-runtime.js";

function absoluteMetadataPath(value) {
  if (typeof value !== "string" || !isAbsolute(value) || value.includes("\0") ||
      value.split(sep).some((part) => part === "." || part === "..")) return undefined;
  return resolve(value);
}

function currentFileSession(event) {
  // Only runtime-owned common fields establish the boundary; tool_input is model-controlled.
  const session = event.session_id;
  if (event.hook_event_name !== "PreToolUse" || !["Read", "Edit", "Write"].includes(event.tool_name) ||
      typeof session !== "string" || !session || session === "." || session === ".." || session.includes(sep) || session.includes("\0")) return undefined;
  const file = event.tool_input?.file_path;
  // Lexically removing '..' before resolving symlinks could hide an escape.
  if (typeof file !== "string" || file.includes("\0") || file.split(sep).includes("..")) return undefined;
  return session;
}

function currentScratchpad(event, session) {
  const directory = absoluteMetadataPath(event.scratchpad_dir);
  if (!directory || basename(directory) !== "scratchpad" || basename(dirname(directory)) !== session) return undefined;
  try {
    return lstatSync(directory).isDirectory() && lstatSync(dirname(directory)).isDirectory() ? directory : undefined;
  } catch {
    return undefined; // An unavailable session directory keeps the original permission decision.
  }
}

function currentToolResults(event, session, cwd) {
  if (event.tool_name !== "Read") return undefined;
  const transcript = absoluteMetadataPath(event.transcript_path);
  const config = absoluteMetadataPath(process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), ".claude"));
  if (!transcript || !config || basename(transcript) !== `${session}.jsonl` ||
      dirname(dirname(transcript)) !== join(config, "projects")) return undefined;
  const project = dirname(transcript);
  const directory = join(project, session, "tool-results");
  try {
    // The runtime's transcript anchors ownership; a lookalike tree or symlink cannot relocate it.
    if (!lstatSync(transcript).isFile() ||
        realpathSync.native(project) !== join(realpathSync.native(config), "projects", basename(project)) ||
        ![project, dirname(directory), directory].every((path) => lstatSync(path).isDirectory()) ||
        !lstatSync(resolve(cwd, event.tool_input.file_path)).isFile()) return undefined;
    return directory;
  } catch {
    return undefined; // Missing or unresolvable runtime metadata keeps the original decision.
  }
}

try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  const cwd = event.cwd || process.cwd();
  const options = { intent: loadPermissionIntent() };
  let result = evaluateRuntimePermission("claude", event, { cwd, project: cwd }, options);
  if (result?.effect === "ask") {
    const session = currentFileSession(event);
    const directories = session ? [currentScratchpad(event, session), currentToolResults(event, session, cwd)] : [];
    if (directories.some((directory) => directory &&
        evaluateRuntimePermission("claude", event, { cwd, project: directory }, options)?.effect === "allow")) {
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

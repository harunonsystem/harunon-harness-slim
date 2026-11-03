/** Claude PreToolUse entry for the shared permission intent. */
import { execFileSync } from "node:child_process";
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

// The runtime-reported <runtime tmp>/<project>/<session>/scratchpad path; it may not exist yet.
function scratchpadMetadata(event, session) {
  const directory = absoluteMetadataPath(event.scratchpad_dir);
  return directory && basename(directory) === "scratchpad" && basename(dirname(directory)) === session ? directory : undefined;
}

function currentScratchpad(event, session) {
  const directory = scratchpadMetadata(event, session);
  if (!directory) return undefined;
  try {
    return lstatSync(directory).isDirectory() && lstatSync(dirname(directory)).isDirectory() ? directory : undefined;
  } catch {
    return undefined; // An unavailable session directory keeps the original permission decision.
  }
}

function transcriptProject(event, session) {
  const transcript = absoluteMetadataPath(event.transcript_path);
  const config = absoluteMetadataPath(process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), ".claude"));
  if (!transcript || !config || basename(transcript) !== `${session}.jsonl` ||
      dirname(dirname(transcript)) !== join(config, "projects")) return undefined;
  const project = dirname(transcript);
  try {
    // The runtime's transcript anchors ownership; a lookalike tree or symlink cannot relocate it.
    return lstatSync(transcript).isFile() && lstatSync(project).isDirectory() &&
      realpathSync.native(project) === join(realpathSync.native(config), "projects", basename(project)) ? project : undefined;
  } catch {
    return undefined; // Missing or unresolvable runtime metadata keeps the original decision.
  }
}

function ownedDirectory(directory, ...ancestors) {
  try {
    return [...ancestors, directory].every((path) => lstatSync(path).isDirectory()) ? directory : undefined;
  } catch {
    return undefined;
  }
}

function currentToolResults(event, session, cwd, project) {
  if (event.tool_name !== "Read" || !project) return undefined;
  const directory = ownedDirectory(join(project, session, "tool-results"), join(project, session));
  try {
    return directory && lstatSync(resolve(cwd, event.tool_input.file_path)).isFile() ? directory : undefined;
  } catch {
    return undefined;
  }
}

// Claude's auto memory for this transcript's project. Edits stay subject to Claude's native rules.
const currentMemory = (project) => project && ownedDirectory(join(project, "memory"));

// Background command output (<runtime tmp>/<project>/<id>/tasks/<name>). After /clear the
// session id changes but tasks keep the process's first id, so any id under this project's root counts.
// The root is derived from scratchpad metadata, not from an existing scratchpad, which is created lazily.
function currentTaskOutputs(event, scratchpad, cwd) {
  if (event.tool_name !== "Read" || !scratchpad) return undefined;
  const file = resolve(cwd, event.tool_input.file_path);
  const directory = dirname(file);
  const root = dirname(dirname(scratchpad));
  if (basename(directory) !== "tasks" || dirname(dirname(directory)) !== root) return undefined;
  try {
    return ownedDirectory(directory, root, dirname(directory)) && lstatSync(file).isFile() ? directory : undefined;
  } catch {
    return undefined;
  }
}

// Distributed skills and rules are instructions the runtime tells the agent to read.
function distributedInstructions(event) {
  if (event.tool_name !== "Read") return [];
  const config = absoluteMetadataPath(process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), ".claude"));
  const agents = join(homedir(), ".agents");
  const roots = [join(agents, "skills"), join(agents, "rules")];
  if (config) roots.push(join(config, "skills"), join(config, "rules"), join(config, "plugins", "cache"));
  return roots.map((root) => ownedDirectory(root));
}

// Another checkout (main or linked worktree) of the cwd's repository. The target's own repository
// decides: cwd's .git/worktrees entries are repository content and could name any directory.
function sameRepositoryCheckout(event, cwd) {
  if (event.tool_name !== "Read") return undefined;
  const revParse = (directory, flag) => execFileSync("git", ["-C", directory, "rev-parse", flag], {
    encoding: "utf8", timeout: 2000, stdio: ["ignore", "pipe", "ignore"],
  }).trim();
  const commonDir = (directory) => realpathSync.native(resolve(directory, revParse(directory, "--git-common-dir")));
  try {
    const target = dirname(resolve(cwd, event.tool_input.file_path));
    return commonDir(target) === commonDir(cwd) ? absoluteMetadataPath(revParse(target, "--show-toplevel")) : undefined;
  } catch {
    return undefined; // Not a repository, a missing directory or git unavailable keeps the original decision.
  }
}

try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  const cwd = event.cwd || process.cwd();
  const options = { intent: loadPermissionIntent() };
  let result = evaluateRuntimePermission("claude", event, { cwd, project: cwd }, options);
  if (result?.effect === "ask") {
    const session = currentFileSession(event);
    const project = session && transcriptProject(event, session);
    const allowedIn = (directory) => directory &&
      evaluateRuntimePermission("claude", event, { cwd, project: directory }, options)?.effect === "allow";
    // git runs only after the cheap filesystem roots fail.
    if (session && ([currentScratchpad(event, session), currentToolResults(event, session, cwd, project), currentMemory(project),
      currentTaskOutputs(event, scratchpadMetadata(event, session), cwd), ...distributedInstructions(event)].some(allowedIn) ||
      allowedIn(sameRepositoryCheckout(event, cwd)))) {
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

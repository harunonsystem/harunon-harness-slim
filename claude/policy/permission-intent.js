/** Semantic permission intent. Adapters must not treat this module as a live guard. */
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const CONTRACT = fileURLToPath(new URL("./permission-intent.json", import.meta.url));
const TARGETS = ["claude", "codex", "pi", "omp", "opencode"];
const CATEGORIES = ["shell", "readEdit", "workspace", "mcp", "publication", "pluginTool", "pluginDirectProcess"];
const REQUIRED_EFFECTS = [
  ["shell.default", "ask"], ["files.secretEffect", "deny"],
  ["files.outsideProject", "ask"], ["mcp.default", "ask"],
  ["pluginTool.default", "ask"],
];

export function loadPermissionIntent(path = CONTRACT) {
  const intent = JSON.parse(readFileSync(path, "utf8"));
  if (intent.version !== 1 || intent.status !== "runtime-wired-partial" || intent.shell?.dangerRules !== "danger-rules.json" ||
      intent.publication?.owner !== "workflow-contract.json" ||
      intent.pluginDirectProcess?.effect !== "unresolved") {
    throw new Error("permission intent: invalid shared references or plugin boundary");
  }
  const actualEffects = [intent.shell.default, intent.files?.secretEffect,
    intent.files?.outsideProject, intent.mcp?.default, intent.pluginTool?.default];
  for (const [index, [label, required]] of REQUIRED_EFFECTS.entries()) {
    if (actualEffects[index] !== required) throw new Error(`permission intent: ${label} must be ${required}`);
  }
  for (const [label, list] of [
    ["files.secretPaths", intent.files.secretPaths], ["files.secretBasenames", intent.files.secretBasenames],
  ]) {
    if (!Array.isArray(list) || !list.length || list.some((item) => typeof item !== "string" || !item)) {
      throw new Error(`permission intent: invalid ${label}`);
    }
  }
  if (intent.files.secretPaths.some((path) => !path.startsWith("~/") && !isAbsolute(path)) ||
      intent.files.secretBasenames.some((name) => name.includes("/") || (name.includes("*") && !name.endsWith("*")))) {
    throw new Error("permission intent: invalid secret path pattern");
  }
  if (Object.keys(intent.targets ?? {}).sort().join() !== [...TARGETS].sort().join()) {
    throw new Error("permission intent: target set differs from supported runtimes");
  }
  for (const target of TARGETS) {
    const claims = intent.targets[target];
    if (Object.keys(claims ?? {}).sort().join() !== [...CATEGORIES].sort().join() ||
        Object.values(claims).some((value) => typeof value !== "string" || !value)) {
      throw new Error(`permission intent: incomplete target capability ${target}`);
    }
    if (claims.pluginDirectProcess !== "unresolved") {
      throw new Error(`permission intent: direct process boundary overclaimed for ${target}`);
    }
  }
  return intent;
}

const homePath = (path) => path === "~" ? homedir() : path.startsWith("~/") ? `${homedir()}${path.slice(1)}` : path;

function canonicalPath(absolute) {
  let ancestor = absolute;
  while (!existsSync(ancestor)) {
    const parent = dirname(ancestor);
    if (parent === ancestor) throw new Error(`permission intent: no existing ancestor: ${absolute}`);
    ancestor = parent;
  }
  return resolve(realpathSync.native(ancestor), relative(ancestor, absolute));
}

function pathPair(raw, cwd) {
  if (typeof raw !== "string" || !raw) throw new Error("permission intent: missing file resource");
  const expanded = homePath(raw);
  const lexical = resolve(isAbsolute(expanded) ? expanded : resolve(cwd, expanded));
  return [lexical, canonicalPath(lexical)];
}

const within = (path, root) => path === root || path.startsWith(`${root}${sep}`);

function isSecret(intent, pair) {
  if (pair.some((path) => intent.files.secretBasenames.some((name) =>
    name.endsWith("*") ? basename(path).startsWith(name.slice(0, -1)) : basename(path) === name))) return true;
  return intent.files.secretPaths.some((pattern) => {
    const tree = pattern.endsWith("/**");
    const root = homePath(tree ? pattern.slice(0, -3) : pattern);
    const roots = pathPair(root, process.cwd());
    return pair.some((path) => roots.some((candidate) => tree ? within(path, candidate) : path === candidate));
  });
}

function fileDecision(intent, action, resource, cwd, project) {
  if (typeof cwd !== "string" || typeof project !== "string" || !isAbsolute(cwd) || !isAbsolute(project)) {
    return { effect: "unresolved", reason: "missing absolute project or cwd" };
  }
  try {
    const pair = pathPair(resource, cwd);
    if (isSecret(intent, pair)) return { effect: intent.files.secretEffect, reason: "secret file" };
    const projectPair = pathPair(project, cwd);
    // Both spellings must stay in their corresponding project root. A symlink
    // inside the project that points outside must still ask.
    if (!pair.every((path, index) => within(path, projectPair[index]))) {
      return { effect: intent.files.outsideProject, reason: "outside project" };
    }
    return { effect: "allow", reason: "project file" };
  } catch {
    return { effect: "unresolved", reason: "file path could not be resolved" };
  }
}

/** A conservative, target-independent decision. `delegate` means use the existing kernel. */
export function decidePermission(intent, { action, resources = [], cwd, project } = {}) {
  if (action === "plugin.directProcess") return { effect: "unresolved", reason: "plugin process boundary undecided" };
  if (action === "publication") return { effect: "delegate", reason: "Core Workflow authorization" };
  if (action === "shell" || action === "workspace") {
    if (!Array.isArray(resources) || resources.length === 0 || resources.some((item) => typeof item !== "string" || !item)) {
      return { effect: "unresolved", reason: "missing resource" };
    }
    return action === "shell" ? { effect: intent.shell.default, reason: "shell command" } :
      { effect: intent.files.outsideProject, reason: "external directory" };
  }
  if (action === "mcp") return { effect: intent.mcp.default, reason: "MCP tool" };
  if (action === "plugin.toolCall") return { effect: intent.pluginTool.default, reason: "plugin tool" };
  if (action !== "read" && action !== "edit") return { effect: "unresolved", reason: `unmapped action: ${action}` };
  if (!Array.isArray(resources) || resources.length === 0) return { effect: "unresolved", reason: "missing file resources" };
  const decisions = resources.map((resource) => fileDecision(intent, action, resource, cwd, project));
  return decisions.find((item) => item.effect === "deny") ??
    decisions.find((item) => item.effect === "unresolved") ??
    decisions.find((item) => item.effect === "ask") ?? decisions[0];
}

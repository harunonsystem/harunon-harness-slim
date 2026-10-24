/** Semantic permission intent. Adapters must not treat this module as a live guard. */
import { lstatSync, readdirSync, readFileSync, realpathSync, statSync } from "node:fs";
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
  const readOnlyTools = intent.mcp?.readOnlyTools;
  if (!Array.isArray(readOnlyTools) || readOnlyTools.some((name) =>
    typeof name !== "string" || !/^mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$/.test(name)) ||
    new Set(readOnlyTools).size !== readOnlyTools.length) {
    throw new Error("permission intent: mcp.readOnlyTools must contain unique exact MCP tool names");
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
  while (true) {
    try {
      lstatSync(ancestor);
      break;
    } catch (error) {
      // A too-long name or a file used as a directory cannot exist, like a missing one.
      if (!["ENOENT", "ENAMETOOLONG", "ENOTDIR"].includes(error.code)) throw error;
      const parent = dirname(ancestor);
      if (parent === ancestor) throw error;
      ancestor = parent;
    }
  }
  // A dangling symlink is an existing boundary, never an uncreated directory.
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

function globSegment(segment) {
  let source = "";
  for (let index = 0; index < segment.length; index++) {
    const character = segment[index];
    if (character === "*") source += ".*";
    else if (character === "?") source += ".";
    else if (character === "[") {
      const end = segment.indexOf("]", index + 2);
      // POSIX classes such as [[:alpha:]] are not read; they count as reachable.
      if (end === -1 || segment.slice(index + 1, end).includes("[")) return undefined;
      source += `[${segment.slice(index + 1, end).replace(/^!/, "^").replace(/\\/g, "\\\\")}]`;
      index = end;
    } else if (character === "{") {
      const end = segment.indexOf("}", index);
      const options = end === -1 ? [] : segment.slice(index + 1, end).split(",");
      // Sequences ({a..z}) and nested patterns are not read; they count as reachable.
      if (options.length < 2 || options.some((option) => /[*?[\]{}]|\.\./.test(option))) return undefined;
      source += `(?:${options.map((option) => option.replace(/[.+^$()|\\]/g, "\\$&")).join("|")})`;
      index = end;
    } else source += character.replace(/[.+^$()|\\\]}]/g, "\\$&");
  }
  return new RegExp(`^${source}$`, "s");
}

/**
 * Whether a glob may name a secret file or reach a secret tree. A glob the shell expands
 * (`listable`) is checked against the directory entries, symlink targets included; a glob a
 * tool applies while walking a tree without following links is checked by name; `filter` marks a
 * search tool's file filter, whose literal value is a name test too. Shapes this cannot read
 * count as reachable.
 */
export function globMayReachSecret(intent, pattern, cwd, { listable = false, filter = false } = {}) {
  // Escapes are not read: `\.e*` would hide its literal prefix.
  if (pattern.includes("\\")) return true;
  const parts = homePath(pattern).split("/");
  let first = parts.findIndex((part) => /[*?[\]{}]/.test(part));
  // A search tool's filter (`--iglob .ENV.local`) selects names even without a wildcard.
  if (first === -1 && !filter) return false;
  if (first === -1) first = parts.length - 1;
  let directory;
  try {
    directory = pathPair(parts.slice(0, first).join("/") || (pattern.startsWith("/") ? "/" : "."), cwd)[1];
  } catch { return true; }
  const roots = intent.files.secretPaths.map((path) => resolve(homePath(path.endsWith("/**") ? path.slice(0, -3) : path)));
  if (roots.some((root) => within(root, directory))) return true;
  const segments = parts.slice(first).map(globSegment);
  if (segments.some((segment) => !segment)) return true;
  if (listable) {
    // A name says nothing about a symlink's target, so the shell's matches are resolved one by one.
    if (segments.length !== 1) return true;
    // A matched directory may be read recursively (rg, grep -r, cp -r), so it counts as reachable.
    try {
      return readdirSync(directory).some((entry) => segments[0].test(entry) &&
        (isSecret(intent, pathPair(resolve(directory, entry), cwd)) || statSync(resolve(directory, entry)).isDirectory()));
    } catch { return true; }
  }
  // A prefix secret (`.env.*`) is unreachable only when the glob's leading literal diverges from it.
  // Case is ignored: tools offer case-insensitive globs and the default macOS filesystem folds case.
  const mayNameSecret = (part, segment) => intent.files.secretBasenames.some((name) => {
    if (!name.endsWith("*")) return new RegExp(segment.source, "si").test(name);
    const prefix = name.slice(0, -1).toLowerCase();
    const literal = part.split(/[*?[{]/)[0].toLowerCase();
    return literal.startsWith(prefix) || prefix.startsWith(literal);
  });
  // Directory segments count too: a secret-named directory (`.env.local/token`) is a secret path.
  return segments.some((segment, index) => mayNameSecret(parts[first + index], segment));
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

// Only a single, literal command can skip shell approval. In particular, no
// quotes, substitutions, redirects, pipelines, environment assignments or
// executable Git options reach this list. Unknown syntax keeps the default ask.
function readOnlyShellPaths(command) {
  if (typeof command !== "string" || !/^[A-Za-z0-9_./:@+ -]+$/.test(command)) return undefined;
  const [program, ...args] = command.trim().split(/ +/);
  if (program === "pwd" && args.length === 0) return [];
  if (program === "mise" && args.length === 2 && args[0] === "settings" && args[1] === "--help") return [];
  if (program === "cat" && args.length > 0 && args.every((arg) => !arg.startsWith("-"))) return args;
  if (program !== "git") return undefined;
  const [subcommand, ...options] = args;
  // Status can execute a configured fsmonitor hook; log can invoke a pager or
  // configured signature verifier. Only fixed rev-parse forms skip approval.
  if (subcommand === "rev-parse" && (
    options.length === 1 && ["HEAD", "--show-toplevel", "--is-inside-work-tree", "--show-prefix"].includes(options[0]) ||
    options.length === 2 && options[0] === "--abbrev-ref" && options[1] === "HEAD"
  )) return [];
  return undefined;
}

export function isReadOnlyShellCommand(intent, command, cwd, project) {
  const paths = readOnlyShellPaths(command);
  return paths !== undefined && [".", ...paths].every((path) => {
    try {
      // The common file rule checks the basename. Shell exceptions also reject
      // secret-named parent directories (for example .env.local/token).
      if (pathPair(path, cwd).some((absolute) => absolute.split(sep).some((part) =>
        intent.files.secretBasenames.some((name) =>
          name.endsWith("*") ? part.startsWith(name.slice(0, -1)) : part === name)))) return false;
    } catch { return false; }
    return fileDecision(intent, "read", path, cwd, project).effect === "allow";
  });
}

/** A conservative, target-independent decision. `delegate` means use the existing kernel. */
export function decidePermission(intent, { action, resources = [], cwd, project } = {}) {
  if (action === "plugin.directProcess") return { effect: "unresolved", reason: "plugin process boundary undecided" };
  if (action === "publication") return { effect: "delegate", reason: "Core Workflow authorization" };
  if (action === "shell" || action === "workspace") {
    if (!Array.isArray(resources) || resources.length === 0 || resources.some((item) => typeof item !== "string" || !item)) {
      return { effect: "unresolved", reason: "missing resource" };
    }
    return action === "shell" ?
      resources.length === 1 && isReadOnlyShellCommand(intent, resources[0], cwd, project) ?
        { effect: "allow", reason: "read-only shell command" } :
        { effect: intent.shell.default, reason: "shell command" } :
      { effect: intent.files.outsideProject, reason: "external directory" };
  }
  if (action === "mcp") return Array.isArray(resources) && resources.length === 1 && intent.mcp.readOnlyTools.includes(resources[0]) ?
    { effect: "allow", reason: "verified read-only MCP tool" } :
    { effect: intent.mcp.default, reason: "MCP tool" };
  if (action === "plugin.toolCall") return { effect: intent.pluginTool.default, reason: "plugin tool" };
  if (action !== "read" && action !== "edit") return { effect: "unresolved", reason: `unmapped action: ${action}` };
  if (!Array.isArray(resources) || resources.length === 0) return { effect: "unresolved", reason: "missing file resources" };
  const decisions = resources.map((resource) => fileDecision(intent, action, resource, cwd, project));
  return decisions.find((item) => item.effect === "deny") ??
    decisions.find((item) => item.effect === "unresolved") ??
    decisions.find((item) => item.effect === "ask") ?? decisions[0];
}

import { resolve } from "node:path";

const RUNTIME_TOOLS = {
  pi: {
    bash: "Bash",
    edit: "Edit",
    write: "Write",
    read: "Read",
    exec_command: "Bash",
    interactive_shell: "Bash",
    apply_patch: "Write",
  },
  omp: {
    bash: "Bash",
    edit: "Edit",
    write: "Write",
    read: "Read",
    exec_command: "Bash",
    interactive_shell: "Bash",
    apply_patch: "Write",
  },
  opencode: {
    bash: "Bash",
  },
  // Codex の tool 名は大文字小文字が揺れるので adapter が小文字化して渡す。
  // apply_patch は file_path を持たず patch envelope を運ぶため Write に寄せる。
  codex: {
    bash: "Bash",
    enterworktree: "EnterWorktree",
    write: "Write",
    write_file: "Write",
    apply_patch: "Write",
    edit: "Edit",
    edit_file: "Edit",
  },
};

// path → file_path / cmd → command の改名が要るのはこの runtime の tool だけ
const RENAMING_RUNTIMES = new Set(["pi", "omp"]);

const PATH_FIELD_TOOLS = new Set(["edit", "write", "read"]);
const COMMAND_FIELD_TOOLS = new Set(["exec_command"]);

function toClaudeInput(runtime, toolName, input) {
  if (RENAMING_RUNTIMES.has(runtime) && PATH_FIELD_TOOLS.has(toolName) && typeof input.path === "string") {
    const { path, ...rest } = input;
    return { ...rest, file_path: path };
  }
  if (RENAMING_RUNTIMES.has(runtime) && COMMAND_FIELD_TOOLS.has(toolName) && typeof input.cmd === "string") {
    const { cmd, ...rest } = input;
    return { ...rest, command: cmd };
  }
  if (runtime === "opencode") {
    return { command: input.command };
  }
  return { ...input };
}

// One resolution for every runtime. Shell tools name the directory argument
// differently (OpenCode 1.18 and pi/omp exec_command: `workdir`; older shapes:
// `cwd`); a per-runtime branch once read only `cwd` for OpenCode and judged
// worktree commands against the session root.
function resolveCwd(input, baseCwd) {
  const selected = [input.workdir, input.cwd].find(
    (value) => typeof value === "string" && value.trim() !== "",
  );
  return selected ? resolve(baseCwd, selected) : baseCwd;
}

/**
 * Convert one host tool call into the Claude hook protocol shape.
 *
 * @returns {{toolName: string, input: Record<string, unknown>, cwd: string}|undefined}
 */
export function normalizeToolCall(runtime, toolName, input, baseCwd) {
  const claudeToolName = RUNTIME_TOOLS[runtime]?.[toolName];
  if (!claudeToolName) return undefined;
  if (runtime === "opencode" && (!input || typeof input !== "object" || typeof input.command !== "string")) {
    return undefined;
  }
  const normalizedInput = toClaudeInput(runtime, toolName, input);
  if (runtime === "omp" && claudeToolName === "Bash" && typeof normalizedInput.command !== "string") {
    return undefined;
  }
  return {
    toolName: claudeToolName,
    input: normalizedInput,
    cwd: resolveCwd(input, baseCwd),
  };
}

const APPLY_PATCH_BEGIN = "*** Begin Patch";
const APPLY_PATCH_END = "*** End Patch";
const PATCH_TARGET = /^\*\*\* (Add File|Update File|Move to): (.+)$/;

/**
 * Cut the apply_patch envelope (Begin..End) out of a command string.
 * pi-codex-conversion applies `apply_patch <<'EOF' ... EOF` inside exec_command directly
 * (tool name stays exec_command), so edit guards and post-edit checks must look into cmd.
 *
 * @returns {string|undefined} undefined when Begin or End is missing
 */
export function extractApplyPatchEnvelope(command) {
  if (typeof command !== "string") return undefined;
  const begin = command.indexOf(APPLY_PATCH_BEGIN);
  if (begin === -1) return undefined;
  const end = command.indexOf(APPLY_PATCH_END, begin);
  if (end === -1) return undefined;
  return command.slice(begin, end + APPLY_PATCH_END.length);
}

function patchTargets(envelope) {
  const paths = [];
  for (const line of envelope.split("\n")) {
    const match = PATCH_TARGET.exec(line.replace(/\r$/, ""));
    if (!match) continue;
    // Move to: replaces the Update File path it follows (the old path no longer exists).
    if (match[1] === "Move to") paths.pop();
    paths.push(match[2].trim());
  }
  return paths;
}

/**
 * Every file a pi / omp tool call writes, resolved to absolute paths. The single place that
 * knows the edit shapes: write/edit `path`, omp hashline multi-file edit `paths[]`, apply_patch
 * `input` envelope, and an apply_patch heredoc inside exec_command `cmd`. Deleted files are
 * not included. Non-edit tools return [].
 *
 * @returns {string[]}
 */
export function editedPaths(toolName, input, baseCwd) {
  if (!input || typeof input !== "object") return [];
  const claudeToolName = RUNTIME_TOOLS.pi[toolName] ?? RUNTIME_TOOLS.omp[toolName];
  let paths = [];
  if (claudeToolName === "Write" || claudeToolName === "Edit") {
    if (typeof input.path === "string") paths = [input.path];
    else if (Array.isArray(input.paths)) paths = input.paths.filter((p) => typeof p === "string");
    else if (typeof input.input === "string") paths = patchTargets(input.input);
  } else if (COMMAND_FIELD_TOOLS.has(toolName)) {
    const envelope = extractApplyPatchEnvelope(input.cmd);
    if (envelope !== undefined) paths = patchTargets(envelope);
  }
  const cwd = resolveCwd(input, baseCwd);
  return [...new Set(paths.filter(Boolean).map((p) => resolve(cwd, p)))];
}

/**
 * Claude hook inputs for one normalized call. Claude Edit/Write carry a single file_path, so an
 * omp hashline multi-file edit (paths[] without path) becomes one input per file; everything
 * else stays a single input.
 *
 * @returns {Record<string, unknown>[]}
 */
export function hookInputsPerFile(normalized, toolName, input) {
  if (normalized.input.file_path !== undefined || !Array.isArray(input?.paths)) return [normalized.input];
  const paths = editedPaths(toolName, input, normalized.cwd);
  if (paths.length === 0) return [normalized.input];
  return paths.map((filePath) => ({ ...normalized.input, file_path: filePath }));
}

/**
 * Map a hookRunner decision onto a pi / omp tool_call response. Both hosts expose
 * ctx.hasUI and ctx.ui.confirm/notify, so ask goes to the confirm dialog and falls back
 * to block only without UI (print / RPC mode).
 *
 * @returns {Promise<{block: true, reason: string}|undefined>}
 */
export async function settleDecision(result, ctx) {
  if (ctx?.hasUI) {
    for (const warning of result.warnings ?? []) ctx.ui.notify(warning, "warning");
  }
  if (result.decision === "allow") return undefined;
  if (result.decision === "ask" && ctx?.hasUI && (await ctx.ui.confirm("Hook 確認", result.reason))) {
    return undefined;
  }
  return { block: true, reason: result.reason || "harness guard hook が理由なしで deny しました" };
}

/**
 * Convert Claude hook input back to the host tool's field names.
 *
 * @returns {Record<string, unknown>}
 */
export function restoreToolInput(runtime, toolName, input) {
  if (runtime === "pi" && PATH_FIELD_TOOLS.has(toolName) && typeof input.file_path === "string") {
    const { file_path: filePath, ...rest } = input;
    return { ...rest, path: filePath };
  }
  if ((runtime === "pi" || runtime === "omp") && COMMAND_FIELD_TOOLS.has(toolName) && typeof input.command === "string") {
    const { command, ...rest } = input;
    return { ...rest, cmd: command };
  }
  return { ...input };
}

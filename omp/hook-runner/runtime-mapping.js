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
};

const PATH_FIELD_TOOLS = new Set(["edit", "write", "read"]);
const COMMAND_FIELD_TOOLS = new Set(["exec_command"]);

function toClaudeInput(runtime, toolName, input) {
  if (runtime !== "opencode" && PATH_FIELD_TOOLS.has(toolName) && typeof input.path === "string") {
    const { path, ...rest } = input;
    return { ...rest, file_path: path };
  }
  if (runtime !== "opencode" && COMMAND_FIELD_TOOLS.has(toolName) && typeof input.cmd === "string") {
    const { cmd, ...rest } = input;
    return { ...rest, command: cmd };
  }
  if (runtime === "opencode") {
    return { command: input.command };
  }
  return { ...input };
}

function resolveCwd(runtime, input, baseCwd) {
  if (runtime === "opencode") {
    if (typeof input.cwd !== "string" || input.cwd.trim() === "") return baseCwd;
    return resolve(baseCwd, input.cwd);
  }
  const workdir = typeof input.workdir === "string" ? input.workdir : undefined;
  const inputCwd = typeof input.cwd === "string" ? input.cwd : undefined;
  const selected = workdir ?? inputCwd;
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
    cwd: resolveCwd(runtime, input, baseCwd),
  };
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

/** Pure input and result projections. This module is not installed as a guard yet. */
import { classifyToolCall } from "./publication-gate.js";
import { editedPaths } from "../hook-runner/runtime-mapping.js";

const SHELL_TOOLS = new Set(["bash", "shell", "exec_command", "interactive_shell"]);
const READ_TOOLS = new Set(["read", "read_file"]);
const EDIT_TOOLS = new Set(["edit", "write", "edit_file", "write_file"]);

const unresolved = (reason, cwd, project) => ({ action: "unresolved", resources: [], cwd, project, reason });

/** Map known host shapes. The caller supplies the already resolved tool cwd. */
export function normalizePermissionEvent(target, event, { cwd, project, mcpActions = [], pluginTools = [] } = {}) {
  if (typeof cwd !== "string" || typeof project !== "string") {
    return unresolved("missing location", cwd, project);
  }
  if (target === "opencode" && typeof event?.action === "string") {
    const resources = Array.isArray(event.resources) ? event.resources : [];
    const action = event.action;
    if ((action === "shell" && resources.some((command) => classifyToolCall("shell", command))) ||
        (mcpActions.includes(action) && classifyToolCall(action))) {
      return { action: "publication", resources, cwd, project };
    }
    if (["read", "edit", "shell", "external_directory"].includes(action)) {
      if (resources.length === 0) return unresolved(`missing ${action} resource`, cwd, project);
      return { action: action === "external_directory" ? "workspace" : action, resources, cwd, project };
    }
    if (mcpActions.includes(action)) return { action: "mcp", resources, cwd, project };
    if (pluginTools.includes(action)) return { action: "plugin.toolCall", resources, cwd, project };
    return unresolved(`unmapped OpenCode action: ${action}`, cwd, project);
  }
  if (!["claude", "codex", "pi", "omp"].includes(target)) return unresolved(`unknown target: ${target}`, cwd, project);
  const name = String(event?.tool_name ?? event?.toolName ?? event?.tool ?? "");
  const tool = name.toLowerCase();
  const input = event?.tool_input ?? event?.input ?? {};
  const command = input.command ?? input.cmd;
  if (SHELL_TOOLS.has(tool) || tool.startsWith("mcp__")) {
    if (classifyToolCall(name, command)) return { action: "publication", resources: [String(command ?? name)], cwd, project };
  }
  if (tool.startsWith("mcp__")) return { action: "mcp", resources: [name], cwd, project };
  if (SHELL_TOOLS.has(tool)) {
    return typeof command === "string" && command ?
      { action: "shell", resources: [command], cwd, project } : unresolved("missing shell command", cwd, project);
  }
  if ((target === "pi" || target === "omp") && (EDIT_TOOLS.has(tool) || tool === "apply_patch")) {
    const resources = editedPaths(tool, input, cwd, { includeRemoved: true });
    const single = input.file_path ?? input.filePath;
    if (!resources.length && tool !== "apply_patch" && typeof single === "string" && single) resources.push(single);
    return resources.length ? { action: "edit", resources, cwd, project } : unresolved("missing edit path", cwd, project);
  }
  if (READ_TOOLS.has(tool) || EDIT_TOOLS.has(tool)) {
    const path = input.file_path ?? input.path ?? input.filePath;
    if (typeof path !== "string" || !path) return unresolved("missing file path", cwd, project);
    return { action: READ_TOOLS.has(tool) ? "read" : "edit", resources: [path], cwd, project };
  }
  if (pluginTools.includes(name)) return { action: "plugin.toolCall", resources: [name], cwd, project };
  return unresolved(`unmapped tool: ${name}`, cwd, project);
}

/** Host hook response capability; a projected decision does not imply the hook is wired. */
export function projectHookEffect(target, effect, { hasUI = false, channel = "tool" } = {}) {
  if (!["claude", "codex", "pi", "omp", "opencode"].includes(target)) throw new Error(`unknown target: ${target}`);
  if (effect === "delegate" || effect === "unresolved") return effect;
  if (!["allow", "ask", "deny"].includes(effect)) throw new Error(`invalid permission effect: ${effect}`);
  if (effect !== "ask") return effect;
  if (target === "claude") return "ask";
  if (target === "opencode") return channel === "permission-v2" ? "ask" : "deny";
  if (target === "codex") return "native"; // PreToolUse cannot prompt; keep Codex's own approval path.
  if (target === "pi" || target === "omp") return hasUI ? "ask" : "deny";
  throw new Error(`unsupported hook projection: ${target}`);
}

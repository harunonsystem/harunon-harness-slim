import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createHarnessPolicy } from "./harness-policy.js";
import { ClaudeHooksBridge } from "./claude-hooks-bridge.js";
import { FixGfmTables } from "./fix-gfm-tables.js";
import { ScanNewSkills } from "./scan-new-skills.js";
import { PostEditChecks } from "./post-edit-checks.js";
import { buildProviderEntries } from "./model-providers.js";
import { workflowToolV2 } from "./harness-workflow-v2.js";
import { loadPermissionIntent } from "../policy/permission-intent.js";
import { evaluateRuntimePermission } from "../policy/permission-runtime.js";
import { normalizePermissionEvent } from "../policy/permission-targets.js";
import { tokenizeShellCommand } from "../policy/pr-action.js";
import { normalizeShellCommand } from "../hook-runner/hook-runner.js";
import { resolveCwd } from "../hook-runner/runtime-mapping.js";

const CATALOG = fileURLToPath(new URL("../model-providers.json", import.meta.url));

function legacyToolName(name) {
  return name === "shell" ? "bash" : name;
}

function legacyInput(event) {
  return { tool: legacyToolName(event.tool), args: event.input };
}

const SEARCH_SCALAR_OPTIONS = new Set([
  "--after-context", "--before-context", "--context", "--context-separator", "--color", "--colors",
  "--encoding", "--engine", "--field-context-separator", "--field-match-separator", "--hyperlink-format",
  "--label", "--max-count", "--max-depth", "--max-filesize", "--path-separator", "--pre-glob",
  "--replace", "--sort", "--sortr", "--threads", "--type", "--type-add", "--type-clear", "--type-not",
]);
const SEARCH_FILE_OPTIONS = new Set(["--file", "--glob", "--iglob", "--ignore-file"]);

function shellFileTokens(tokens) {
  const files = [];
  let program, patternPending, filePending, scalarPending, optionsEnded;
  for (const token of tokens) {
    const value = token.value;
    if (token.separator) { program = undefined; patternPending = filePending = scalarPending = optionsEnded = false; continue; }
    if (token.redirection) { filePending = true; continue; }
    if (filePending) { files.push(token); filePending = false; continue; }
    if (scalarPending) { scalarPending = false; continue; }
    if (!program) {
      if (["rtk", "command", "env", "exec", "sudo", "nice", "time", "nohup"].includes(value) ||
          value.startsWith("-") || /^[A-Za-z_][A-Za-z0-9_]*=/.test(value)) continue;
      program = value.split("/").at(-1);
      patternPending = ["rg", "grep", "egrep", "fgrep"].includes(program);
      files.push({ ...token, program: true });
      continue;
    }
    if (["rg", "grep", "egrep", "fgrep"].includes(program)) {
      if (value === "--" && !optionsEnded) { optionsEnded = true; continue; }
      if (!optionsEnded) {
        const [option, ...attached] = value.split("=");
        if (option === "--regexp") { patternPending = !attached.length; continue; }
        if (SEARCH_FILE_OPTIONS.has(option)) {
          if (option === "--file") patternPending = false;
          if (attached.length) files.push({ ...token, value: attached.join("=") });
          else filePending = true;
          continue;
        }
        if (SEARCH_SCALAR_OPTIONS.has(option)) { scalarPending = !attached.length; continue; }
        if (program === "rg" && value.startsWith("-r") && !value.startsWith("--")) {
          scalarPending = value === "-r"; continue;
        }
        const short = /^-[A-Za-z]*?([efgABCmjtTE])(.*)$/.exec(value);
        if (short) {
          const [, flag, argument] = short;
          if (flag === "e") patternPending = !argument;
          else if (flag === "f" || flag === "g") {
            if (flag === "f") patternPending = false;
            if (argument) files.push({ ...token, value: argument });
            else filePending = true;
          } else scalarPending = !argument;
          continue;
        }
        if (patternPending && value.startsWith("-")) continue;
      }
      if (patternPending) { patternPending = false; continue; }
    }
    files.push(token);
  }
  return files;
}

export async function setupHarunonV2(ctx, { hooksDir, tablePath, authorizePr, invokeKernel } = {}) {
  if (existsSync(CATALOG)) {
    const catalog = JSON.parse(readFileSync(CATALOG, "utf8"));
    if (Object.keys(buildProviderEntries(catalog)).length > 0) {
      throw new Error("OpenCode v2 provider transform is required for non-native harness providers");
    }
  }

  const base = ctx.location.directory;
  const intent = loadPermissionIntent();
  const danger = JSON.parse(readFileSync(new URL("../policy/danger-rules.json", import.meta.url), "utf8"));
  const shellRules = danger.rules.flatMap((rule) => {
    if (!rule.targets.includes("opencode")) return [];
    const action = rule.overrides?.opencode?.action ?? rule.action;
    if (!["block", "confirm"].includes(action)) return [];
    return (rule.match?.globs?.opencode ?? []).map((glob) => ({
      effect: action === "block" ? "deny" : "ask",
      reason: rule.id,
      pattern: new RegExp(danger.constants.originJs + "(?:rtk\\s+)?" + glob.split("*").map(
        (part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      ).join(".*") + "(?=$|[;&|\\n])"),
    }));
  });
  const shellSafety = (commands, cwd = base) => {
    let pending;
    for (const command of commands) {
      const tokens = tokenizeShellCommand(command);
      const files = shellFileTokens(tokens ?? []);
      const inlineCode = files.some((token) => token.program &&
        /(?:^|\/)(?:python[0-9.]*|node|bash|sh|zsh|ruby|perl)$/.test(token.value)) &&
        tokens.some((token) => /^(?:-[cep]|--eval(?:=|$))/.test(token.value));
      if (!tokens || inlineCode || tokens.some((token) => token.dynamic ||
          // 引用符内の [] {} は jq 式やテンプレートで shell は展開しない。* と ? はツール自身が
          // 展開しうるので引用符内でも確認する。
          ["cd", "eval"].includes(token.value)) || files.some((token) => token.glob || /[*?]/.test(token.value))) {
        pending = { effect: "ask", reason: "dynamic shell command" };
      }
      const paths = files.flatMap(
        (token) => [token.value, ...token.value.split(/[\s"'()<>=;&|/]+/)]
      ).filter(Boolean);
      if (paths.length) {
        const files = evaluateRuntimePermission("opencode", { action: "read", resources: paths },
          { cwd, project: ctx.location.project?.canonical ?? base }, { intent, channel: "permission-v2" });
        if (files?.effect === "deny") return files;
      }
      let normalized;
      try { normalized = normalizeShellCommand(command).replace(/[ \t]+/g, " ").trim(); }
      catch { return { effect: "deny", reason: "shell normalization unavailable" }; }
      if (normalized.split(/[;&|\n]+/).some((statement) => /^(?:-|(?:rtk )?git -)/.test(statement.trim()))) {
        pending = { effect: "ask", reason: "unresolved shell wrapper" };
      }
      for (const rule of shellRules) {
        if (!normalized.split(/[;&|\n]+/).some((statement) => rule.pattern.test(statement.trim()))) continue;
        if (rule.effect === "deny") return rule;
        pending = rule;
      }
    }
    return pending;
  };
  const policy = await createHarnessPolicy(authorizePr)({ directory: base });
  const bridge = await ClaudeHooksBridge({ directory: base, hooksDir, tablePath });
  const scan = await ScanNewSkills({});
  const postEdit = await PostEditChecks({ hooksDir });
  const tables = await FixGfmTables({});

  await ctx.tool.transform((editor) => editor.add(workflowToolV2(base, invokeKernel)));

  await ctx.permission.hook("evaluate", (event) => {
    const location = { cwd: base, project: ctx.location.project?.canonical ?? base };
    if (event.action === "shell") {
      const safety = shellSafety(event.resources ?? []);
      if (safety && event.effect !== "deny") {
        event.effect = safety.effect;
        event.message = safety.reason;
        return;
      }
    }
    if (normalizePermissionEvent("opencode", event, location).action === "publication") return;
    const verdict = evaluateRuntimePermission("opencode", event, {
      ...location,
    }, { intent, channel: "permission-v2" });
    if (!verdict) return;
    if (event.action === "shell" && verdict.effect === "allow" && event.effect === "ask") {
      event.effect = "allow";
      event.message = verdict.reason;
      return;
    }
    // Native rules own ordinary shell and external-directory approvals; the shared
    // fallback is not a veto of those rules. File denials still tighten native policy.
    if (verdict.effect === "deny") {
      event.effect = verdict.effect;
      event.message = verdict.reason;
    }
  });

  await ctx.tool.hook("execute.before", async (event) => {
    if (event.tool === "shell" && (!event.input || typeof event.input.command !== "string")) {
      throw new Error("OpenCode shell call has no command for harness guards");
    }
    if (event.tool === "shell") {
      const safety = shellSafety([event.input.command], resolveCwd(event.input, base));
      if (safety?.effect === "deny") throw new Error(safety.reason);
    }
    const input = legacyInput(event);
    const output = { args: event.input };
    await policy["tool.execute.before"](input, output);
    await bridge["tool.execute.before"](input, output);
    event.input = output.args;
  });

  await ctx.tool.hook("execute.after", async (event) => {
    if (event.status !== "completed") return;
    const input = legacyInput(event);
    if (input.tool === "edit" || input.tool === "write") {
      input.args = { ...input.args, filePath: input.args?.path ?? input.args?.filePath };
    }
    const original = event.result.content;
    const initial = typeof original === "string" ? original : "";
    const output = { output: initial };
    await scan["tool.execute.after"](input, output);
    await postEdit["tool.execute.after"](input, output);
    if (output.output !== initial) {
      const content = Array.isArray(original)
        ? [...original, { type: "text", text: output.output }]
        : output.output;
      event.result = { ...event.result, content };
    }
  });

  const controller = new AbortController();
  void (async () => {
    while (!controller.signal.aborted) {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event.type === "file.edited") {
            try {
              await tables.event({ event: { type: "file.edited", properties: { file: event.data?.file } } });
            } catch (eventError) {
              console.error("[harunon] file.edited handler failed", eventError);
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("[harunon] file event stream failed", error);
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    }
  })();
  return () => controller.abort();
}

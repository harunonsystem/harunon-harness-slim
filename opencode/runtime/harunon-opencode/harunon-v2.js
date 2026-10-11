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

const CATALOG = fileURLToPath(new URL("../model-providers.json", import.meta.url));
const NATIVE_OTHER_ACTIONS = new Set(["glob", "grep", "subagent", "skill", "question", "webfetch", "websearch", "execute", "plan_enter", "plan_exit"]);

function legacyToolName(name) {
  return name === "shell" ? "bash" : name;
}

function legacyInput(event) {
  return { tool: legacyToolName(event.tool), args: event.input };
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
  const policy = await createHarnessPolicy(authorizePr)({ directory: base });
  const bridge = await ClaudeHooksBridge({ directory: base, hooksDir, tablePath });
  const scan = await ScanNewSkills({});
  const postEdit = await PostEditChecks({ hooksDir });
  const tables = await FixGfmTables({});

  await ctx.tool.transform((editor) => editor.add(workflowToolV2(base, invokeKernel)));

  await ctx.permission.hook("evaluate", (event) => {
    const location = { cwd: base, project: ctx.location.project?.canonical ?? base };
    if (normalizePermissionEvent("opencode", event, location).action === "publication") return;
    const verdict = evaluateRuntimePermission("opencode", event, {
      ...location,
    }, { intent, channel: "permission-v2" });
    if (!verdict) {
      // Unknown custom and MCP actions still pass through V2's native prompt.
      // Configured denies are final before this hook, and native built-ins retain their policy.
      if (!NATIVE_OTHER_ACTIONS.has(event.action) && event.effect === "allow") {
        event.effect = "ask";
        event.message = "Unclassified tool permission requires approval";
      }
      return;
    }
    if (verdict.effect === "deny" || (verdict.effect === "ask" && event.effect === "allow")) {
      event.effect = verdict.effect;
      event.message = verdict.reason;
    }
  });

  await ctx.tool.hook("execute.before", async (event) => {
    if (event.tool === "shell" && (!event.input || typeof event.input.command !== "string")) {
      throw new Error("OpenCode shell call has no command for harness guards");
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
    try {
      for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
        if (event.type === "file.edited") {
          await tables.event({ event: { type: "file.edited", properties: { file: event.data?.file } } });
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) console.error("[harunon] file event stream failed", error);
    }
  })();
  return () => controller.abort();
}

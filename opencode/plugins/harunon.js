import { HarnessPolicy } from "../runtime/harunon-opencode/harness-policy.js";
import { ClaudeHooksBridge } from "../runtime/harunon-opencode/claude-hooks-bridge.js";
import { FixGfmTables } from "../runtime/harunon-opencode/fix-gfm-tables.js";
import { ScanNewSkills } from "../runtime/harunon-opencode/scan-new-skills.js";
import { ModelProviders } from "../runtime/harunon-opencode/model-providers.js";
import { PostEditChecks } from "../runtime/harunon-opencode/post-edit-checks.js";
import { setupHarunonV2 } from "../runtime/harunon-opencode/harunon-v2.js";

const PLUGINS = [
  HarnessPolicy,
  ClaudeHooksBridge,
  FixGfmTables,
  ScanNewSkills,
  ModelProviders,
  PostEditChecks,
];

function compose(instances) {
  const handlers = new Map();
  const tools = {};
  for (const instance of instances) {
    for (const [event, handler] of Object.entries(instance)) {
      if (event === "tool") {
        Object.assign(tools, handler);
        continue;
      }
      const eventHandlers = handlers.get(event) ?? [];
      eventHandlers.push(handler);
      handlers.set(event, eventHandlers);
    }
  }
  return {
    tool: tools,
    ...Object.fromEntries(
      [...handlers].map(([event, eventHandlers]) => [
        event,
        async (...args) => {
          for (const handler of eventHandlers) await handler(...args);
        },
      ]),
    ),
  };
}

const Harunon = async (context) => {
  const instances = [];
  const { HarnessWorkflow } = await import("../runtime/harunon-opencode/harness-workflow.js");
  instances.push(await HarnessWorkflow(context));
  for (const plugin of PLUGINS) instances.push(await plugin(context));
  return compose(instances);
};

export default {
  id: "harunon-harness",
  setup: setupHarunonV2,
  server: Harunon,
};

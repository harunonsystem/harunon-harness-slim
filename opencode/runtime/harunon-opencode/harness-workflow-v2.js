import { compileWorkflowRequest, invokeKernel } from "./harness-workflow-core.js";
import { resolveToolCwd } from "./tool-cwd.js";

const OPERATIONS = [
  "inspect", "verify", "complete", "start", "advance", "approve_review",
  "attach_review", "skip_review", "assign", "dispatched", "report",
  "abandon", "authorize",
];

const STRING_FIELDS = [
  "cwd", "taskId", "event", "provider", "subjectSha", "artifact", "reason",
  "executor", "workerId", "transport", "ref", "at", "resultSha", "checks",
];

export function workflowToolV2(base, run = invokeKernel) {
  return {
    name: "harness_workflow",
    description: "Inspect or advance Core Workflow. Pass cwd for another worktree.",
    input: {
      type: "object",
      properties: {
        operation: { type: "string", enum: OPERATIONS },
        ...Object.fromEntries(STRING_FIELDS.map((name) => [name, { type: "string" }])),
        expectedRevision: { type: "integer" },
        mode: { type: "string", enum: ["change", "publish"] },
        role: { type: "string", enum: ["implement", "review"] },
        action: { type: "string", enum: ["pr.create", "pr.merge"] },
      },
      required: ["operation"],
      additionalProperties: false,
    },
    async execute(input) {
      const cwd = resolveToolCwd(base, input.cwd);
      const content = await run("operate", compileWorkflowRequest(input), cwd);
      return { content };
    },
  };
}

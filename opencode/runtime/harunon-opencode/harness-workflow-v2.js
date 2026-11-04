import { compileWorkflowRequest, invokeKernel } from "./harness-workflow-core.js";
import { resolveCwd } from "../hook-runner/runtime-mapping.js";

const OPERATIONS = [
  "inspect", "verify", "complete", "start", "advance", "approve_review",
  "attach_review", "attach_publication_body", "skip_review", "authorize",
];

const STRING_FIELDS = ["cwd", "taskId", "event", "provider", "subjectSha", "artifact", "reason", "command"];

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
        action: { type: "string", enum: ["pr.create", "pr.update-body", "pr.merge"] },
        publication: { type: "object", properties: {
          body: { type: "string" }, number: { type: "integer" }, repository: { type: "string" },
          headBranch: { type: "string" }, headRepository: { type: "string" }, bodyError: { type: "string" },
        }, additionalProperties: false },
      },
      required: ["operation"],
      additionalProperties: false,
    },
    async execute(input) {
      const cwd = resolveCwd(input, base);
      const content = await run("operate", compileWorkflowRequest(input), cwd);
      return { content };
    },
  };
}

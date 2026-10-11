import { tool } from "@opencode-ai/plugin";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";
import { compileWorkflowRequest, invokeKernel } from "./harness-workflow-core.js";

export const HarnessWorkflow = async ({ invokeKernel: run = invokeKernel } = {}) => ({
  tool: {
    harness_workflow: tool({
      description:
        "Inspect or advance the shared Core Workflow without shell commands. " +
        "Pass cwd when the task lives in a worktree other than the session directory " +
        "(state is per git worktree).",
      args: {
        operation: tool.schema.enum([
          "inspect",
          "verify",
          "complete",
          "start",
          "advance",
          "approve_review",
          "attach_review",
          "skip_review",
          "assign",
          "dispatched",
          "report",
          "abandon",
          "authorize",
        ]),
        cwd: tool.schema.string().optional(),
        taskId: tool.schema.string().optional(),
        mode: tool.schema.enum(["change", "publish"]).optional(),
        event: tool.schema.string().optional(),
        expectedRevision: tool.schema.number().int().optional(),
        provider: tool.schema.string().optional(),
        subjectSha: tool.schema.string().optional(),
        artifact: tool.schema.string().optional(),
        reason: tool.schema.string().optional(),
        role: tool.schema.enum(["implement", "review"]).optional(),
        executor: tool.schema.string().optional(),
        workerId: tool.schema.string().optional(),
        transport: tool.schema.string().optional(),
        ref: tool.schema.string().optional(),
        at: tool.schema.string().optional(),
        resultSha: tool.schema.string().optional(),
        checks: tool.schema.string().optional(),
        action: tool.schema.enum(["pr.create", "pr.merge"]).optional(),
      },
      async execute(args, context) {
        const request = compileWorkflowRequest(args);
        // bash tool の cwd 引数と同じ規約: 独立 worktree で作業しているセッションは
        // cwd を渡さないと親リポジトリの state（別タスク）を掴んで ACTIVE_TASK_EXISTS になる
        return run("operate", request, resolveToolCwd(sessionBaseCwd(context), args.cwd));
      },
    }),
  },
});

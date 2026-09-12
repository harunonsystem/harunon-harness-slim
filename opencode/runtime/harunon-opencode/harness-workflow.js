import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { tool } from "@opencode-ai/plugin";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";

const KERNEL = fileURLToPath(new URL("../policy/harnessctl.py", import.meta.url));

function invoke(command, request, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [KERNEL, command], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", reject);
    child.on("close", (code) => {
      const output = stdout.trim() || stderr.trim();
      if (code === 0) resolve(output);
      else reject(new Error(output || `harnessctl exited ${code}`));
    });
    child.stdin.end(JSON.stringify({ repo: cwd, ...request }));
  });
}

function compile(args) {
  if (args.operation === "inspect") return ["inspect", {}];
  if (args.operation === "start") {
    return ["apply", { type: "task.start", taskId: args.taskId }];
  }
  if (args.operation === "advance") {
    return [
      "apply",
      { type: "phase.advance", event: args.event, expectedRevision: args.expectedRevision },
    ];
  }
  if (args.operation === "approve_review") {
    return [
      "apply",
      {
        type: "review.approve",
        reason: args.reason,
        expectedRevision: args.expectedRevision,
      },
    ];
  }
  if (args.operation === "attach_review") {
    return [
      "apply",
      {
        type: "review.attach",
        expectedRevision: args.expectedRevision,
        evidence: {
          kind: "local-review",
          trust: "audit-only",
          provider: args.provider,
          subjectSha: args.subjectSha,
          artifact: args.artifact,
        },
      },
    ];
  }
  if (args.operation === "assign") {
    return [
      "apply",
      {
        type: "assignment.create",
        expectedRevision: args.expectedRevision,
        role: args.role,
        executor: args.executor,
        workerId: args.workerId,
      },
    ];
  }
  if (args.operation === "dispatched") {
    return [
      "apply",
      {
        type: "assignment.dispatched",
        expectedRevision: args.expectedRevision,
        transport: args.transport,
        ref: JSON.parse(args.ref),
        at: args.at,
      },
    ];
  }
  if (args.operation === "report") {
    return [
      "apply",
      {
        type: "assignment.report",
        expectedRevision: args.expectedRevision,
        evidence: {
          kind: "worker-report",
          trust: "audit-only",
          executor: args.executor,
          workerId: args.workerId,
          resultSha: args.resultSha,
          artifact: args.artifact,
          checks: JSON.parse(args.checks || "[]"),
        },
      },
    ];
  }
  if (args.operation === "abandon") {
    return [
      "apply",
      {
        type: "assignment.abandon",
        expectedRevision: args.expectedRevision,
        reason: args.reason,
      },
    ];
  }
  return ["authorize", { action: args.action }];
}

export const HarnessWorkflow = async ({ invokeKernel = invoke } = {}) => ({
  tool: {
    harness_workflow: tool({
      description:
        "Inspect or advance the shared Core Workflow without shell commands. " +
        "Pass cwd when the task lives in a worktree other than the session directory " +
        "(state is per git worktree).",
      args: {
        operation: tool.schema.enum([
          "inspect",
          "start",
          "advance",
          "approve_review",
          "attach_review",
          "assign",
          "dispatched",
          "report",
          "abandon",
          "authorize",
        ]),
        cwd: tool.schema.string().optional(),
        taskId: tool.schema.string().optional(),
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
        const [command, request] = compile(args);
        // bash tool の cwd 引数と同じ規約: 独立 worktree で作業しているセッションは
        // cwd を渡さないと親リポジトリの state（別タスク）を掴んで ACTIVE_TASK_EXISTS になる
        return invokeKernel(command, request, resolveToolCwd(sessionBaseCwd(context), args.cwd));
      },
    }),
  },
});

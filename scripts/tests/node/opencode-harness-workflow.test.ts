import { test } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

const mockModule = `
const schema = new Proxy({}, { get: () => () => schema });
export const tool = Object.assign((definition) => definition, { schema });
`;
registerHooks({
	resolve(specifier, context, nextResolve) {
		if (specifier === "@opencode-ai/plugin") {
			return { url: `data:text/javascript,${encodeURIComponent(mockModule)}`, shortCircuit: true };
		}
		return nextResolve(specifier, context);
	},
});

const { HarnessWorkflow } = await import(
	"../../../packages/core/opencode-plugins/harness-workflow.js"
);

type Invocation = { command: string; request: Record<string, unknown>; cwd: string };

async function execute(args: Record<string, unknown>): Promise<Invocation> {
	let invocation: Invocation | undefined;
	const plugin = await HarnessWorkflow({
		invokeKernel: async (command: string, request: Record<string, unknown>, cwd: string) => {
			invocation = { command, request, cwd };
			return "ok";
		},
	});
	await plugin.tool.harness_workflow.execute(args, { directory: "/repo", worktree: "/worktree" });
	assert.ok(invocation);
	return invocation;
}

test("assignment operations compile to exact kernel requests", async () => {
	const common = { expectedRevision: 7, cwd: "/task" };
	assert.deepEqual(await execute({ operation: "assign", ...common, role: "implement", executor: "codex", workerId: "w1" }), {
		command: "apply",
		cwd: "/task",
		request: { type: "assignment.create", expectedRevision: 7, role: "implement", executor: "codex", workerId: "w1" },
	});
	assert.deepEqual(await execute({ operation: "dispatched", ...common, transport: "agmsg", ref: '{"team":"h","to":"worker"}', at: "2026-09-05T00:00:00Z" }), {
		command: "apply",
		cwd: "/task",
		request: { type: "assignment.dispatched", expectedRevision: 7, transport: "agmsg", ref: { team: "h", to: "worker" }, at: "2026-09-05T00:00:00Z" },
	});
	assert.deepEqual(await execute({ operation: "report", ...common, executor: "codex", workerId: "w1", resultSha: "abc", artifact: "/tmp/report", checks: '[{"command":"pytest","exitCode":0}]' }), {
		command: "apply",
		cwd: "/task",
		request: { type: "assignment.report", expectedRevision: 7, evidence: { kind: "worker-report", trust: "audit-only", executor: "codex", workerId: "w1", resultSha: "abc", artifact: "/tmp/report", checks: [{ command: "pytest", exitCode: 0 }] } },
	});
	assert.deepEqual(await execute({ operation: "abandon", ...common, reason: "stopped" }), {
		command: "apply",
		cwd: "/task",
		request: { type: "assignment.abandon", expectedRevision: 7, reason: "stopped" },
	});
});

test("invalid assignment JSON and kernel rejection propagate", async () => {
	const plugin = await HarnessWorkflow({
		invokeKernel: async () => {
			throw new Error("kernel rejected");
		},
	});
	const run = plugin.tool.harness_workflow.execute;
	await assert.rejects(
		run({ operation: "dispatched", expectedRevision: 1, ref: "{" }, { directory: "/repo" }),
		SyntaxError,
	);
	await assert.rejects(
		run({ operation: "abandon", expectedRevision: 1, reason: "x" }, { directory: "/repo" }),
		/kernel rejected/,
	);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
	createToolCallHandler,
	extractApplyPatchEnvelope,
	toClaudeInput,
	toPiInput,
	type BridgeContext,
	type HookRunResult,
	type HookRunner,
} from "../../../packages/core/pi-extensions/claude-hooks-bridge.ts";

// pi adapter のテスト。wire protocol は hookRunner 側（hook-runner.test.ts）が持つので、
// ここでは runner を stub し「pi の event をどう Claude 名 / tool_input / cwd に写し、
// decision を pi の応答にどう戻すか」だけを見る。

interface Call {
	toolName: string;
	toolInput: Record<string, unknown>;
	cwd: string;
}

function stubRunner(
	respond: (call: Call) => Partial<HookRunResult> = () => ({}),
): HookRunner & { calls: Call[] } {
	const calls: Call[] = [];
	return {
		calls,
		async preToolUse(toolName, toolInput, cwd) {
			const call = { toolName, toolInput, cwd };
			calls.push(call);
			return { decision: "allow", reason: "", finalInput: toolInput, warnings: [], ...respond(call) };
		},
	};
}

function contextWith(overrides: Partial<BridgeContext>): BridgeContext {
	return {
		hasUI: false,
		ui: { confirm: async () => false, notify: () => undefined },
		cwd: process.cwd(),
		...overrides,
	};
}

test("toClaudeInput / toPiInput は edit/write/read の path と file_path、exec_command の cmd と command を双方向変換する", () => {
	assert.deepEqual(toClaudeInput("edit", { path: "/tmp/a.ts", edits: [] }), { file_path: "/tmp/a.ts", edits: [] });
	assert.deepEqual(toPiInput("write", { file_path: "/tmp/a.ts", content: "x" }), { path: "/tmp/a.ts", content: "x" });
	assert.deepEqual(toClaudeInput("bash", { command: "ls" }), { command: "ls" });
	assert.deepEqual(toClaudeInput("exec_command", { cmd: "ls -la", workdir: "/x" }), { command: "ls -la", workdir: "/x" });
	assert.deepEqual(toPiInput("exec_command", { command: "rtk ls -la", workdir: "/x" }), { cmd: "rtk ls -la", workdir: "/x" });
	// apply_patch の input（patch text）はキー名を変換せずそのまま通す
	assert.deepEqual(toClaudeInput("apply_patch", { input: "*** Begin Patch ***" }), { input: "*** Begin Patch ***" });
});

test("extractApplyPatchEnvelope は Begin〜End を切り出し、End が無ければ undefined", () => {
	const envelope = "*** Begin Patch\n*** Update File: a.txt\n*** End Patch";
	assert.equal(extractApplyPatchEnvelope(`apply_patch <<'P'\n${envelope}\nP\n`), envelope);
	assert.equal(extractApplyPatchEnvelope("*** Begin Patch\nno end"), undefined);
	assert.equal(extractApplyPatchEnvelope("ls"), undefined);
});

test("マップ外のツールは runner を呼ばず素通しする", async () => {
	const runner = stubRunner();
	const response = await createToolCallHandler(runner)({ toolName: "unknown_tool", input: { x: 1 } }, contextWith({}));
	assert.equal(response, undefined);
	assert.deepEqual(runner.calls, []);
});

test("deny は block:true と理由を返す", async () => {
	const runner = stubRunner(() => ({ decision: "deny", reason: "no" }));
	const response = await createToolCallHandler(runner)({ toolName: "bash", input: { command: "rg foo" } }, contextWith({}));
	assert.deepEqual(response, { block: true, reason: "no" });
	assert.equal(runner.calls[0].toolName, "Bash");
});

test("finalInput は event.input に書き戻される（exec_command は cmd へ）", async () => {
	const runner = stubRunner((call) => ({ finalInput: { ...call.toolInput, command: "rtk " + call.toolInput.command } }));
	const bash = { toolName: "bash", input: { command: "git status" } };
	assert.equal(await createToolCallHandler(runner)(bash, contextWith({})), undefined);
	assert.equal(bash.input.command, "rtk git status");

	const exec = { toolName: "exec_command", input: { cmd: "ls -la" } };
	assert.equal(await createToolCallHandler(runner)(exec, contextWith({})), undefined);
	assert.equal(exec.input.cmd, "rtk ls -la");
	assert.equal("command" in exec.input, false);
});

test("edit ツールは Edit / file_path として runner に渡り、pi 側の input は path のまま保たれる", async () => {
	const runner = stubRunner();
	const event = { toolName: "edit", input: { path: "/tmp/a.ts", edits: [] } };
	assert.equal(await createToolCallHandler(runner)(event, contextWith({})), undefined);
	assert.equal(runner.calls[0].toolName, "Edit");
	assert.deepEqual(runner.calls[0].toolInput, { file_path: "/tmp/a.ts", edits: [] });
	assert.deepEqual(event.input, { path: "/tmp/a.ts", edits: [] });
});

test("apply_patch は Write として渡り、input（patch text）はそのまま tool_input.input で見える", async () => {
	const runner = stubRunner();
	const patchText = "*** Begin Patch\n*** Update File: a.txt\n*** End Patch";
	await createToolCallHandler(runner)({ toolName: "apply_patch", input: { input: patchText } }, contextWith({}));
	assert.equal(runner.calls[0].toolName, "Write");
	assert.equal(runner.calls[0].toolInput.input, patchText);
});

test("interactive_shell の raw command は Bash hooks に渡る", async () => {
	const runner = stubRunner();
	const event = { toolName: "interactive_shell", input: { command: "git status", mode: "interactive" } };
	const response = await createToolCallHandler(runner)(event, contextWith({}));
	assert.equal(response, undefined);
	assert.equal(runner.calls[0].toolName, "Bash");
	assert.deepEqual(runner.calls[0].toolInput, { command: "git status", mode: "interactive" });
});

test("interactive_shell の破壊的 raw command は Bash hooks で block される", async () => {
	const runner = stubRunner(() => ({ decision: "deny", reason: "interactive command denied" }));
	const response = await createToolCallHandler(runner)(
		{ toolName: "interactive_shell", input: { command: "rm -rf ./build" } },
		contextWith({}),
	);
	assert.deepEqual(response, { block: true, reason: "interactive command denied" });
});

test("exec_command の cmd に埋め込まれた apply_patch heredoc は Write hooks にも envelope で渡り、deny なら exec_command 自体を block する", async () => {
	const envelope = "*** Begin Patch\n*** Update File: a.txt\n*** End Patch";
	const cmd = `apply_patch <<'PATCH'\n${envelope}\nPATCH\n`;
	const runner = stubRunner();
	assert.equal(await createToolCallHandler(runner)({ toolName: "exec_command", input: { cmd } }, contextWith({})), undefined);
	assert.deepEqual(
		runner.calls.map((c) => [c.toolName, c.toolInput]),
		[
			["Bash", { command: cmd }],
			["Write", { file_path: "", input: envelope }],
		],
	);

	const denying = stubRunner((call) =>
		call.toolName === "Write" ? { decision: "deny", reason: "main direct edit" } : {},
	);
	const response = await createToolCallHandler(denying)({ toolName: "exec_command", input: { cmd } }, contextWith({}));
	assert.deepEqual(response, { block: true, reason: "main direct edit" });
});

test("ask は UI 承認で通し、拒否と非 UI では block する", async () => {
	const runner = stubRunner(() => ({ decision: "ask", reason: "確認して" }));
	const handler = createToolCallHandler(runner);
	const event = () => ({ toolName: "bash", input: { command: "x" } });
	const ui = (answer: boolean) => contextWith({ hasUI: true, ui: { confirm: async () => answer, notify: () => undefined } });
	assert.equal(await handler(event(), ui(true)), undefined);
	assert.deepEqual(await handler(event(), ui(false)), { block: true, reason: "確認して" });
	assert.deepEqual(await handler(event(), contextWith({ hasUI: false })), { block: true, reason: "確認して" });
});

test("warnings は UI があれば notify に流れる", async () => {
	const runner = stubRunner(() => ({ warnings: ["boom"] }));
	const notified: string[] = [];
	await createToolCallHandler(runner)(
		{ toolName: "bash", input: { command: "x" } },
		contextWith({ hasUI: true, ui: { confirm: async () => false, notify: (m) => notified.push(m) } }),
	);
	assert.deepEqual(notified, ["boom"]);
});

test("cwd: workdir > input.cwd > ctx.cwd の順で、ctx.cwd 基準に解決して runner へ渡す", async () => {
	const runner = stubRunner();
	const handler = createToolCallHandler(runner);
	const base = realpathSync(mkdtempSync(join(tmpdir(), "handler-base-")));
	mkdirSync(join(base, "sub"));
	const workDir = realpathSync(mkdtempSync(join(tmpdir(), "handler-workdir-")));
	const inputDir = realpathSync(mkdtempSync(join(tmpdir(), "handler-input-")));

	await handler({ toolName: "exec_command", input: { cmd: "ls", workdir: workDir } }, contextWith({ cwd: base }));
	await handler({ toolName: "bash", input: { command: "x" } }, contextWith({ cwd: base }));
	await handler({ toolName: "bash", input: { command: "x", cwd: inputDir } }, contextWith({ cwd: base }));
	await handler({ toolName: "bash", input: { command: "x", cwd: "sub" } }, contextWith({ cwd: base }));
	assert.deepEqual(
		runner.calls.map((c) => c.cwd),
		[workDir, base, inputDir, resolve(base, "sub")],
	);
});

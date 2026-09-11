import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHookRunner } from "../../../packages/core/hook-runner/hook-runner.js";
import ompDenialReason, {
	createDenialReasonHandler,
} from "../../../packages/core/omp-extensions/omp-denial-reason.js";
import { REAL_HOOKS_DIR, REAL_TABLE_PATH, fixtureLayout, fixtureScript } from "./_fixtures.ts";

// omp adapter のテスト。wire protocol は hookRunner 側（hook-runner.test.ts）が持つので、
// ここでは「bash の tool_call を runner にどう渡し、decision を block にどう写すか」だけを見る。

const ctx = { cwd: process.cwd() };
const bashCall = (command: string) => ({ toolName: "bash", toolCallId: "t1", input: { command } });

function handlerFor(layout: { dir: string; tablePath: string }) {
	return createDenialReasonHandler(
		createHookRunner({ runtime: "omp", hooksDir: layout.dir, tablePath: layout.tablePath }),
	);
}

test("tool_call に登録される", () => {
	const events: string[] = [];
	ompDenialReason({ on: (name: string) => events.push(name) });
	assert.deepEqual(events, ["tool_call"]);
});

test("deny → block with the hook's stderr as reason / allow → undefined", async () => {
	const layout = fixtureLayout("omp-denial-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", `cat > /dev/null\necho "approve-push.sh を実行してください" >&2\nexit 2`);
	assert.deepEqual(await handlerFor(layout)(bashCall("git push"), ctx), {
		block: true,
		reason: "approve-push.sh を実行してください",
	});
	fixtureScript(layout.dir, "guard.sh", `cat > /dev/null\nexit 0`);
	assert.equal(await handlerFor(layout)(bashCall("echo hi"), ctx), undefined);
});

test("deny に理由が無ければ定型文で block する", async () => {
	const layout = fixtureLayout("omp-denial-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", `cat > /dev/null\nexit 2`);
	const result = await handlerFor(layout)(bashCall("x"), ctx);
	assert.equal(result?.block, true);
	assert.match(result!.reason, /理由なしで deny/);
});

test("missing hook → block that names the distribution gap (no silent fail-open)", async () => {
	const layout = fixtureLayout("omp-denial-", [{ file: "guard.sh", required: true }]);
	const handler = createDenialReasonHandler(
		createHookRunner({ runtime: "omp", hooksDir: join(layout.dir, "nope"), tablePath: layout.tablePath }),
	);
	const result = await handler(bashCall("echo hi"), ctx);
	assert.equal(result?.block, true);
	assert.match(result!.reason, /required security hook missing: guard\.sh/);
	assert.match(result!.reason, /bootstrap\.sh --targets omp/);
});

test("non-bash tools and bash without a command string are ignored", async () => {
	const layout = fixtureLayout("omp-denial-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", `exit 2`);
	const handler = handlerFor(layout);
	assert.equal(await handler({ toolName: "edit", toolCallId: "t", input: { path: "x" } }, ctx), undefined);
	assert.equal(await handler({ toolName: "bash", toolCallId: "t", input: {} }, ctx), undefined);
});

test("hook runs with HARNESS_RUNTIME=omp, PreToolUse stdin and the cwd resolved against ctx.cwd", async () => {
	const layout = fixtureLayout("omp-denial-", [{ file: "guard.sh", required: true }]);
	const dir = realpathSync(mkdtempSync(join(tmpdir(), "omp-denial-cwd-")));
	mkdirSync(join(dir, "sub"));
	fixtureScript(layout.dir, "guard.sh", `cat > "${dir}/seen.json"\necho "rt=$HARNESS_RUNTIME pwd=$PWD" >&2\nexit 2`);
	const result = await handlerFor(layout)(
		{ toolName: "bash", toolCallId: "t", input: { command: "ls", cwd: "sub" } },
		{ cwd: dir },
	);
	assert.equal(result?.block, true);
	assert.match(result!.reason, new RegExp(`rt=omp pwd=${dir}/sub$`));
	const seen = JSON.parse(readFileSync(`${dir}/seen.json`, "utf8"));
	assert.equal(seen.tool_name, "Bash");
	assert.equal(seen.tool_input.command, "ls");
	assert.equal(seen.hook_event_name, "PreToolUse");
});

test("integration: the real table wires only block-dangerous to omp; it denies git reset --hard and allows echo", async () => {
	const runner = createHookRunner({ runtime: "omp", hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH });
	assert.deepEqual(runner.hooks("Bash"), ["block-dangerous-in-bash.sh"]);
	const handler = createDenialReasonHandler(runner);
	const denied = await handler(bashCall("git reset --hard HEAD"), ctx);
	assert.equal(denied?.block, true);
	assert.match(denied!.reason, /git reset --hard/);
	assert.equal(await handler(bashCall("echo hi"), ctx), undefined);
});

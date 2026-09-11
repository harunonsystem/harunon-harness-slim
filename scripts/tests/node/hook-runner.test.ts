import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	createHookRunner,
	selectHooks,
} from "../../../packages/core/hook-runner/hook-runner.js";
import {
	REAL_HOOKS_DIR,
	REAL_TABLE_PATH,
	fixtureLayout,
	fixtureScript,
	withEnv,
	writeTable,
} from "./_fixtures.ts";

// hookRunner の interface（preToolUse）越しに wire protocol と table 駆動の選択を検証する。
// 3 runtime の adapter はこの module を共有するので、ここが通れば protocol はどの runtime でも同じ。

const REWRITE_JSON =
	'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"rewrite","updatedInput":{"command":"rtk git status"}}}';
const ASK_JSON =
	'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"危険かも"}}';

function runnerFor(layout: { dir: string; tablePath: string }, runtime = "pi") {
	return createHookRunner({ runtime, hooksDir: layout.dir, tablePath: layout.tablePath });
}

test("table が読めなければ runner の生成が throw する（fail loud）", () => {
	assert.throws(
		() => createHookRunner({ runtime: "pi", tablePath: "/nonexistent/hook-pipeline.json" }),
		/hook-pipeline\.json を読み込めません/,
	);
});

test("selectHooks は runtime・when.tools で絞り order 昇順に並べる", () => {
	const dir = mkdtempSync(join(tmpdir(), "runner-"));
	const table = JSON.parse(
		readFileSync(
			writeTable(dir, [
				{ file: "rewrite.sh", order: 100, stage: "rewrite" },
				{ file: "guard.sh", order: 10 },
				{ file: "edit-guard.sh", order: 50, tools: ["Write", "Edit"] },
				{ file: "opencode-only.sh", order: 20, runtimes: ["opencode"] },
			]),
			"utf8",
		),
	);
	assert.deepEqual(
		selectHooks(table, "pi", "Bash").map((h: { file: string }) => h.file),
		["guard.sh", "rewrite.sh"],
	);
	assert.deepEqual(
		selectHooks(table, "opencode", "Bash").map((h: { file: string }) => h.file),
		["guard.sh", "opencode-only.sh", "rewrite.sh"],
	);
	assert.deepEqual(
		selectHooks(table, "pi", "Edit").map((h: { file: string }) => h.file),
		["edit-guard.sh"],
	);
	assert.deepEqual(selectHooks(table, "pi", "Read"), []);
});

test("when.commandEre に一致しないコマンドでは hook を spawn しない", async () => {
	const layout = fixtureLayout("runner-", [
		{ file: "grep-guard.sh", commandEre: "(?:^|[;&|\\n]\\s*)(?:e?grep|fgrep|sed|awk)\\b" },
	]);
	fixtureScript(layout.dir, "grep-guard.sh", 'echo "ran" >&2\nexit 2');
	const runner = runnerFor(layout);
	assert.equal((await runner.preToolUse("Bash", { command: "ls" }, layout.dir)).decision, "allow");
	assert.equal(
		(await runner.preToolUse("Bash", { command: "grep foo bar" }, layout.dir)).decision,
		"deny",
	);
});

test("exit 2 の hook は stderr を理由に deny する", async () => {
	const layout = fixtureLayout("runner-", [{ file: "deny.sh" }]);
	fixtureScript(layout.dir, "deny.sh", 'echo "blocked by fixture" >&2\nexit 2');
	const result = await runnerFor(layout).preToolUse("Bash", { command: "rg foo" }, layout.dir);
	assert.equal(result.decision, "deny");
	assert.equal(result.reason, "blocked by fixture");
});

test("stdin を読まずに即 exit 2 する hook でも EPIPE にならず deny が返る", async () => {
	const layout = fixtureLayout("runner-", [{ file: "deny.sh" }]);
	fixtureScript(layout.dir, "deny.sh", 'echo "blocked without reading" >&2\nexit 2');
	// pipe バッファ (64KB) を超える stdin で、hook 終了後の write を確実に EPIPE させる
	const result = await runnerFor(layout).preToolUse(
		"Bash",
		{ command: "rg " + "x".repeat(1024 * 1024) },
		layout.dir,
	);
	assert.equal(result.decision, "deny");
	assert.equal(result.reason, "blocked without reading");
});

test("updatedInput は後続 hook に連鎖して最終 input に反映される", async () => {
	const layout = fixtureLayout("runner-", [
		{ file: "rewrite.sh", order: 10 },
		{ file: "capture.sh", order: 20 },
	]);
	fixtureScript(layout.dir, "rewrite.sh", `cat > /dev/null\ncat <<'EOF'\n${REWRITE_JSON}\nEOF`);
	fixtureScript(layout.dir, "capture.sh", `cat > "${layout.dir}/seen.json"`);
	const result = await runnerFor(layout).preToolUse(
		"Bash",
		{ command: "git status", timeout: 1 },
		layout.dir,
	);
	assert.equal(result.decision, "allow");
	assert.deepEqual(result.finalInput, { command: "rtk git status", timeout: 1 });
	const seen = JSON.parse(readFileSync(join(layout.dir, "seen.json"), "utf8"));
	assert.equal(seen.tool_input.command, "rtk git status");
	assert.equal(seen.tool_name, "Bash");
	assert.equal(seen.hook_event_name, "PreToolUse");
	assert.equal(seen.cwd, layout.dir);
});

test("permissionDecision deny / ask は decision にそのまま写る", async () => {
	const layout = fixtureLayout("runner-", [{ file: "ask.sh" }]);
	fixtureScript(layout.dir, "ask.sh", `cat > /dev/null\necho '${ASK_JSON}'`);
	const asked = await runnerFor(layout).preToolUse("Bash", { command: "x" }, layout.dir);
	assert.equal(asked.decision, "ask");
	assert.equal(asked.reason, "危険かも");

	fixtureScript(
		layout.dir,
		"ask.sh",
		`cat > /dev/null\necho '{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"policy says no"}}'`,
	);
	const denied = await runnerFor(layout).preToolUse("Bash", { command: "x" }, layout.dir);
	assert.equal(denied.decision, "deny");
	assert.equal(denied.reason, "policy says no");
});

test("advisory hook の exit 1 / 非 JSON stdout / ファイル欠落は warning のみで続行する", async () => {
	const layout = fixtureLayout("runner-", [
		{ file: "broken.sh", order: 10 },
		{ file: "not-json.sh", order: 20 },
		{ file: "missing.sh", order: 30 },
	]);
	fixtureScript(layout.dir, "broken.sh", 'echo "oops" >&2\nexit 1');
	fixtureScript(layout.dir, "not-json.sh", 'cat > /dev/null\necho "not json at all"');
	rmSync(join(layout.dir, "missing.sh"));
	const result = await runnerFor(layout).preToolUse("Bash", { command: "x" }, layout.dir);
	assert.equal(result.decision, "allow");
	assert.equal(result.warnings.length, 2);
	assert.match(result.warnings[0], /hook failed \(exit 1\): broken\.sh: oops/);
	assert.match(result.warnings[1], /stdout is not JSON: not-json\.sh/);
});

test("required hook の exit 1 は deny する（M-004）", async () => {
	const layout = fixtureLayout("runner-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", 'echo "oops" >&2\nexit 1');
	const result = await runnerFor(layout).preToolUse("Bash", { command: "x" }, layout.dir);
	assert.equal(result.decision, "deny");
	assert.match(result.reason, /required security hook failed \(exit 1\): guard\.sh: oops/);
});

test("required hook の stdout が JSON として壊れていると deny する", async () => {
	const layout = fixtureLayout("runner-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", 'cat > /dev/null\necho "not json at all"');
	const result = await runnerFor(layout).preToolUse("Bash", { command: "x" }, layout.dir);
	assert.equal(result.decision, "deny");
	assert.match(result.reason, /required security hook stdout is not JSON: guard\.sh/);
});

test("required hook のファイル欠落はコマンド内容に関係なく deny し、bootstrap を案内する", async () => {
	const layout = fixtureLayout("runner-", [
		{ file: "guard.sh", required: true, commandEre: "\\bnever-matches\\b" },
	]);
	rmSync(join(layout.dir, "guard.sh"));
	const result = await runnerFor(layout, "omp").preToolUse("Bash", { command: "echo hi" }, layout.dir);
	assert.equal(result.decision, "deny");
	assert.match(result.reason, /required security hook missing: guard\.sh/);
	assert.match(result.reason, /bootstrap\.sh --targets omp/);
});

test("hooks dir が丸ごと無くても required hook 欠落として deny する", async () => {
	const dir = mkdtempSync(join(tmpdir(), "runner-"));
	const tablePath = writeTable(dir, [{ file: "guard.sh", required: true }]);
	const runner = createHookRunner({ runtime: "pi", hooksDir: join(dir, "nope"), tablePath });
	const result = await runner.preToolUse("Bash", { command: "x" }, dir);
	assert.equal(result.decision, "deny");
	assert.match(result.reason, /required security hook missing/);
});

test("hook プロセスには HARNESS_RUNTIME と、/bin を含む PATH が渡る", async () => {
	const layout = fixtureLayout("runner-", [{ file: "capture.sh" }]);
	fixtureScript(
		layout.dir,
		"capture.sh",
		`cat > /dev/null\necho -n "$HARNESS_RUNTIME" > "${layout.dir}/runtime.txt"`,
	);
	await withEnv("PATH", "/definitely/no/bash", async () => {
		const result = await runnerFor(layout, "opencode").preToolUse("Bash", { command: "x" }, layout.dir);
		assert.equal(result.decision, "allow");
	});
	assert.equal(readFileSync(join(layout.dir, "runtime.txt"), "utf8"), "opencode");
});

test("存在しない cwd では spawn error を hook 失敗として扱う（advisory は warning、required は deny）", async () => {
	const layout = fixtureLayout("runner-", [{ file: "advisory.sh" }]);
	const missingCwd = join(layout.dir, "does-not-exist");
	const advisory = await runnerFor(layout).preToolUse("Bash", { command: "x" }, missingCwd);
	assert.equal(advisory.decision, "allow");
	assert.match(advisory.warnings[0], /spawn failed/);

	const strict = fixtureLayout("runner-", [{ file: "guard.sh", required: true }]);
	const required = await runnerFor(strict).preToolUse("Bash", { command: "x" }, join(strict.dir, "nope"));
	assert.equal(required.decision, "deny");
	assert.match(required.reason, /spawn failed/);
});

test("hooks(toolName) は table が runtime に配線する hook を order 順で返す", () => {
	const runner = createHookRunner({ runtime: "pi", hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH });
	assert.deepEqual(runner.hooks("Bash"), [
		"block-grep-in-bash.sh",
		"block-dangerous-in-bash.sh",
		"enforce-gwm-for-worktree.sh",
		"block-secrets-in-commit.sh",
		"rtk-rewrite.sh",
	]);
	assert.deepEqual(runner.hooks("Edit"), ["block-edit-on-main.sh"]);
	assert.deepEqual(
		createHookRunner({ runtime: "omp", hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH }).hooks("Bash"),
		["block-dangerous-in-bash.sh"],
	);
});

test("実 table + 実 hook: block-grep-in-bash.sh が grep 直叩きを deny する", async () => {
	const runner = createHookRunner({ runtime: "pi", hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH });
	const result = await runner.preToolUse("Bash", { command: "grep -r foo ." }, process.cwd());
	assert.equal(result.decision, "deny");
	assert.match(result.reason, /rg/);
});

test("実 table + 実 hook: 危険操作の承認手順が deny 理由へ届く", async () => {
	const runner = createHookRunner({ runtime: "pi", hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH });
	const flagDir = mkdtempSync(join(tmpdir(), "runner-approval-"));
	await withEnv("CODEX_REVIEW_FLAG_DIR", flagDir, async () => {
		const result = await runner.preToolUse("Bash", { command: "gh pr merge 123" }, process.cwd());
		assert.equal(result.decision, "deny");
		assert.match(result.reason, /approve-pr\.sh/);
	});
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHookRunner } from "../../../packages/core/hook-runner/hook-runner.js";
import { ClaudeHooksBridge } from "../../../packages/core/opencode-plugins/claude-hooks-bridge.js";
import { createDenialReasonHandler } from "../../../packages/core/omp-extensions/omp-denial-reason.js";
import {
	createToolCallHandler,
	type BridgeContext,
} from "../../../packages/core/pi-extensions/claude-hooks-bridge.ts";
import { REPO_ROOT, fixtureScript, writeTable, type FixtureHook } from "./_fixtures.ts";

// 同じ fixture を pi / opencode / omp の adapter に流し、正規化した結果が
// scripts/tests/fixtures/hook-protocol.json の宣言と一致することを確認する。
// wire protocol 自体は hookRunner 1 本なので、ここで見えるのは adapter がホストへ
// decision を写す部分（ask を UI に出せるか / updatedInput を書き戻すか）の差だけ。
// 契約は実行時に読まれないため policy/ には置かない（5 runtime へ無駄に配布される）。
const CONTRACT = JSON.parse(
	readFileSync(join(REPO_ROOT, "scripts/tests/fixtures/hook-protocol.json"), "utf8"),
);

type Outcome = {
	decision: "allow" | "deny" | "ask" | "rewrite";
	reason?: string;
	rewrittenCommand?: string;
	mergesOtherFields?: boolean;
	/** hook が実際に受け取った spawn cwd（$PWD）が、adapter に渡したセッション base と一致したか */
	sessionBaseMatches?: boolean;
};

const RECEIVED_CWD_FILE = "received-cwd.txt";
const HOOK_FILE = "hook.sh";

/**
 * case 宣言から hook スクリプトの本体を作る。stdin は必ず読み捨てる（EPIPE 回避）。
 * 併せて自身の $PWD を dir 直下へ常時記録する（session-base-cwd pin 用。他 case は無視してよい）。
 */
function hookBody(dir: string, spec: Record<string, any>): string {
	const lines = ["cat > /dev/null", `echo -n "$PWD" > "${join(dir, RECEIVED_CWD_FILE)}"`];
	if (spec.stderr) lines.push(`echo ${JSON.stringify(spec.stderr)} >&2`);
	if (spec.rawStdout) lines.push(`echo ${JSON.stringify(spec.rawStdout)}`);
	if (spec.decision) {
		const payload = {
			hookSpecificOutput: {
				hookEventName: "PreToolUse",
				permissionDecision: spec.decision,
				permissionDecisionReason: spec.reason ?? "",
				...(spec.updatedInput ? { updatedInput: spec.updatedInput } : {}),
			},
		};
		lines.push(`cat <<'JSONEOF'\n${JSON.stringify(payload)}\nJSONEOF`);
	}
	lines.push(`exit ${spec.exit ?? 0}`);
	return lines.join("\n");
}

/** advisory の単一 hook を全 runtime に配線した layout。generic な protocol 以外の deny を発生させない。 */
function layoutFor(prefix: string, spec: Record<string, any>): { dir: string; tablePath: string } {
	const dir = mkdtempSync(join(tmpdir(), prefix));
	fixtureScript(dir, HOOK_FILE, hookBody(dir, spec));
	return { dir, tablePath: writeTable(dir, [{ file: HOOK_FILE }]) };
}

function sessionBaseMatches(dir: string): boolean {
	return realpathSync(readFileSync(join(dir, RECEIVED_CWD_FILE), "utf8")) === realpathSync(dir);
}

const INPUT = { command: "git status", timeout: 1 };

function outcomeFrom(
	dir: string,
	input: Record<string, unknown>,
	spec: Record<string, any>,
): Outcome {
	if (input.command !== "git status") {
		return {
			decision: "rewrite",
			rewrittenCommand: String(input.command),
			mergesOtherFields: input.timeout === spec.updatedInput?.timeout,
			sessionBaseMatches: sessionBaseMatches(dir),
		};
	}
	return { decision: "allow", sessionBaseMatches: sessionBaseMatches(dir) };
}

async function runOpencode(spec: Record<string, any>): Promise<Outcome> {
	const { dir, tablePath } = layoutFor("conf-oc-", spec);
	const plugin = await ClaudeHooksBridge({ directory: dir, worktree: undefined, hooksDir: dir, tablePath });
	const output = { args: { ...INPUT } };
	try {
		await plugin["tool.execute.before"]({ tool: "bash" }, output);
	} catch (error) {
		return { decision: "deny", reason: String((error as Error).message), sessionBaseMatches: sessionBaseMatches(dir) };
	}
	return outcomeFrom(dir, output.args, spec);
}

async function runPi(spec: Record<string, any>): Promise<Outcome> {
	const { dir, tablePath } = layoutFor("conf-pi-", spec);
	let asked = false;
	const context: BridgeContext = {
		hasUI: true,
		ui: {
			confirm: async () => {
				asked = true;
				return false;
			},
			notify: () => undefined,
		},
		cwd: dir,
	};
	const event = { toolName: "bash", input: { ...INPUT } as Record<string, unknown> };
	const runner = createHookRunner({ runtime: "pi", hooksDir: dir, tablePath });
	const response: any = await createToolCallHandler(runner)(event, context);
	if (asked) return { decision: "ask", sessionBaseMatches: sessionBaseMatches(dir) };
	if (response?.block) return { decision: "deny", reason: String(response.reason ?? ""), sessionBaseMatches: sessionBaseMatches(dir) };
	return outcomeFrom(dir, event.input, spec);
}

async function runOmp(spec: Record<string, any>): Promise<Outcome> {
	const { dir, tablePath } = layoutFor("conf-omp-", spec);
	const runner = createHookRunner({ runtime: "omp", hooksDir: dir, tablePath });
	const event = { toolName: "bash", toolCallId: "t", input: { ...INPUT } as Record<string, unknown> };
	const response: any = await createDenialReasonHandler(runner)(event, { cwd: dir });
	if (response?.block) return { decision: "deny", reason: String(response.reason ?? ""), sessionBaseMatches: sessionBaseMatches(dir) };
	return outcomeFrom(dir, event.input, spec);
}

function runCodexFixture(
	prefix: string,
	setup: (root: string, hooksDir: string) => FixtureHook[],
): { root: string; stdout: string } {
	const root = mkdtempSync(join(tmpdir(), prefix));
	const hooksDir = join(root, "hooks");
	const policyDir = join(root, "policy");
	const scriptsDir = join(root, "scripts");
	mkdirSync(hooksDir);
	mkdirSync(policyDir);
	mkdirSync(scriptsDir);
	const tablePath = writeTable(root, setup(root, hooksDir));
	copyFileSync(tablePath, join(policyDir, "hook-pipeline.json"));
	copyFileSync(
		join(REPO_ROOT, "packages/runtimes/codex/harunon-core/scripts/codex_hook.py"),
		join(scriptsDir, "codex_hook.py"),
	);
	const result = spawnSync("python3", [join(scriptsDir, "codex_hook.py")], {
		cwd: root,
		input: JSON.stringify({
			hook_event_name: "PreToolUse",
			tool_name: "Bash",
			tool_input: { ...INPUT },
			cwd: root,
		}),
		encoding: "utf8",
	});
	assert.equal(result.status, 0, result.stderr);
	return { root, stdout: result.stdout.trim() };
}

async function runCodex(spec: Record<string, any>): Promise<Outcome> {
	const { root, stdout } = runCodexFixture("conf-codex-", (dir, hooksDir) => {
		fixtureScript(hooksDir, HOOK_FILE, hookBody(dir, spec));
		return [{ file: HOOK_FILE }];
	});
	if (!stdout) return { decision: "allow", sessionBaseMatches: sessionBaseMatches(root) };
	let payload: any;
	try {
		payload = JSON.parse(stdout);
	} catch {
		return { decision: "deny", reason: `invalid hook output: ${stdout}`, sessionBaseMatches: sessionBaseMatches(root) };
	}
	const output = payload.hookSpecificOutput ?? {};
	if (output.permissionDecision === "deny") {
		return { decision: "deny", reason: String(output.permissionDecisionReason ?? ""), sessionBaseMatches: sessionBaseMatches(root) };
	}
	if (output.permissionDecision === "ask") {
		return { decision: "ask", sessionBaseMatches: sessionBaseMatches(root) };
	}
	if (output.updatedInput) {
		return {
			decision: "rewrite",
			rewrittenCommand: String(output.updatedInput.command),
			mergesOtherFields: output.updatedInput.timeout === spec.updatedInput?.timeout,
			sessionBaseMatches: sessionBaseMatches(root),
		};
	}
	return { decision: "allow", sessionBaseMatches: sessionBaseMatches(root) };
}

function runCodexPipeline(
	hooks: Array<{ file: string; body: string; required?: boolean }>,
): Record<string, any> | undefined {
	const { stdout } = runCodexFixture("conf-codex-pipeline-", (_root, hooksDir) => {
		for (const hook of hooks) fixtureScript(hooksDir, hook.file, hook.body);
		return hooks.map(({ file, required }) => ({ file, required }));
	});
	return stdout ? JSON.parse(stdout) : undefined;
}

const RUNNERS: Record<string, (spec: Record<string, any>) => Promise<Outcome>> = {
	pi: runPi,
	opencode: runOpencode,
	omp: runOmp,
	codex: runCodex,
};

for (const testCase of CONTRACT.cases) {
	for (const [runtime, run] of Object.entries(RUNNERS)) {
		const declared = testCase.divergence?.[runtime] ?? testCase.expect;
		const label = testCase.divergence?.[runtime] ? "divergence" : "expect";
		test(`[${runtime}] ${testCase.id} (${label})`, async () => {
			const actual = await run(testCase.hook);
			assert.equal(
				actual.decision,
				declared.decision,
				`${testCase.description}\n実測=${JSON.stringify(actual)}`,
			);
			if (declared.reasonContains) {
				assert.match(actual.reason ?? "", new RegExp(declared.reasonContains));
			}
			if (declared.rewrittenCommand) {
				assert.equal(actual.rewrittenCommand, declared.rewrittenCommand);
			}
			if (declared.mergesOtherFields !== undefined) {
				assert.equal(
					actual.mergesOtherFields,
					declared.mergesOtherFields,
					"updatedInput の command 以外のフィールドの扱いが宣言と違う",
				);
			}
			if (declared.receivedCwd === "sessionBase") {
				assert.equal(
					actual.sessionBaseMatches,
					true,
					"hook が受け取った spawn cwd がセッション base と一致しない",
				);
			}
		});
	}
}

test("[codex] later required hooks run after advisory output", () => {
	const allow = JSON.stringify({ hookSpecificOutput: { permissionDecision: "allow" } });
	const payload = runCodexPipeline([
		{ file: "advisory.sh", body: `cat > /dev/null\necho '${allow}'` },
		{ file: "required.sh", required: true, body: "cat > /dev/null\necho 'required denied' >&2\nexit 2" },
	]);
	assert.equal(payload?.hookSpecificOutput.permissionDecision, "deny");
	assert.match(payload?.hookSpecificOutput.permissionDecisionReason, /required denied/);
});

test("[codex] advisory failures do not skip a later required success", () => {
	const payload = runCodexPipeline([
		{ file: "advisory.sh", body: "cat > /dev/null\nexit 1" },
		{ file: "required.sh", required: true, body: "cat > /dev/null\nexit 0" },
	]);
	assert.equal(payload, undefined);
});

test("[codex] required failures fail closed", () => {
	const payload = runCodexPipeline([
		{ file: "required.sh", required: true, body: "cat > /dev/null\necho 'required crashed' >&2\nexit 1" },
	]);
	assert.equal(payload?.hookSpecificOutput.permissionDecision, "deny");
	assert.match(payload?.hookSpecificOutput.permissionDecisionReason, /required crashed/);
});

test("[codex] updatedInput feeds the next hook", () => {
	const rewrite = JSON.stringify({ hookSpecificOutput: { permissionDecision: "allow", updatedInput: { command: "rtk git status" } } });
	const deny = JSON.stringify({ hookSpecificOutput: { permissionDecision: "deny", permissionDecisionReason: "saw rewrite" } });
	const payload = runCodexPipeline([
		{ file: "rewrite.sh", body: `cat > /dev/null\necho '${rewrite}'` },
		{ file: "observe.sh", required: true, body: `input=$(cat)\nif [[ "$input" == *"rtk git status"* ]]; then echo '${deny}'; else exit 2; fi` },
	]);
	assert.equal(payload?.hookSpecificOutput.permissionDecision, "deny");
	assert.equal(payload?.hookSpecificOutput.permissionDecisionReason, "Core Workflow blocked shell.guard: saw rewrite");
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClaudeHooksBridge } from "../../../packages/core/opencode-plugins/claude-hooks-bridge.js";
import {
	REAL_HOOKS_DIR,
	REAL_TABLE_PATH,
	fixtureLayout,
	fixtureScript,
	withEnv,
} from "./_fixtures.ts";

// OpenCode adapter のテスト。wire protocol と required fail-closed は hookRunner 側
// （hook-runner.test.ts）が持つので、ここでは「bash の tool.execute.before を runner に
// どう渡し、decision を throw / args 書き戻しにどう写すか」だけを見る。

const REWRITE_JSON =
	'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","updatedInput":{"command":"rtk git status","timeout":1234}}}';

async function pluginFor(layout: { dir: string; tablePath: string }, extra: Record<string, unknown> = {}) {
	return ClaudeHooksBridge({ directory: layout.dir, worktree: undefined, hooksDir: layout.dir, tablePath: layout.tablePath, ...extra });
}

test("deny（exit 2）は理由を message に throw する", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", 'echo "blocked by fixture" >&2\nexit 2');
	const plugin = await pluginFor(layout);
	await assert.rejects(
		plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "grep foo bar.txt" } }),
		/blocked by fixture/,
	);
});

test("permissionDecision ask は deny 相当で throw する（OpenCode に確認 UI はない）", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "ask.sh" }]);
	fixtureScript(
		layout.dir,
		"ask.sh",
		`cat > /dev/null\necho '{"hookSpecificOutput":{"permissionDecision":"ask","permissionDecisionReason":"危険かも"}}'`,
	);
	const plugin = await pluginFor(layout);
	await assert.rejects(plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "x" } }), /危険かも/);
});

test("updatedInput は output.args に丸ごと書き戻され、2 本目の hook は書き換え後を見る", async () => {
	const layout = fixtureLayout("ocb-", [
		{ file: "rewrite.sh", order: 10 },
		{ file: "capture.sh", order: 20 },
	]);
	fixtureScript(layout.dir, "rewrite.sh", `cat > /dev/null\ncat <<'EOF'\n${REWRITE_JSON}\nEOF`);
	fixtureScript(layout.dir, "capture.sh", `cat > "${layout.dir}/seen.json"`);
	const plugin = await pluginFor(layout);
	const output = { args: { command: "git status", cwd: layout.dir } };
	await plugin["tool.execute.before"]({ tool: "bash" }, output);
	assert.equal(output.args.command, "rtk git status");
	assert.equal((output.args as Record<string, unknown>).timeout, 1234);
	const seen = JSON.parse(readFileSync(join(layout.dir, "seen.json"), "utf8"));
	assert.equal(seen.tool_input.command, "rtk git status");
});

test("advisory hook の exit 1 は fail-open: throw せずコマンドは変更されない", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "advisory.sh" }]);
	fixtureScript(layout.dir, "advisory.sh", 'echo "oops" >&2\nexit 1');
	const plugin = await pluginFor(layout);
	const output = { args: { command: "x" } };
	await plugin["tool.execute.before"]({ tool: "bash" }, output);
	assert.equal(output.args.command, "x");
});

test("input.tool が bash 以外、または command が無ければ hook を呼ばない", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "guard.sh", required: true }]);
	fixtureScript(layout.dir, "guard.sh", 'echo "should not run" >&2\nexit 2');
	const plugin = await pluginFor(layout);
	await assert.doesNotReject(plugin["tool.execute.before"]({ tool: "edit" }, { args: { command: "x" } }));
	await assert.doesNotReject(plugin["tool.execute.before"]({ tool: "bash" }, { args: {} }));
});

test("hooks dir が未配布なら required hook 欠落として bash を deny する（fail-closed）", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "guard.sh", required: true }]);
	const plugin = await pluginFor(layout, { hooksDir: join(layout.dir, "missing") });
	await assert.rejects(
		plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "x" } }),
		/required security hook missing: guard\.sh.*bootstrap\.sh --targets opencode/,
	);
});

test("spawn cwd と stdin .cwd は bash tool の cwd 引数 > worktree > directory の順で決まり、HARNESS_RUNTIME=opencode が渡る", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "capture.sh" }]);
	fixtureScript(
		layout.dir,
		"capture.sh",
		`echo -n "$PWD" > "${layout.dir}/pwd.txt"\necho -n "$HARNESS_RUNTIME" > "${layout.dir}/runtime.txt"\ncat > "${layout.dir}/seen.json"`,
	);
	const worktreeDir = mkdtempSync(join(tmpdir(), "ocb-worktree-"));
	const directoryDir = mkdtempSync(join(tmpdir(), "ocb-directory-"));
	const toolCwd = mkdtempSync(join(tmpdir(), "ocb-toolcwd-"));
	const seenCwd = () => realpathSync(JSON.parse(readFileSync(join(layout.dir, "seen.json"), "utf8")).cwd);
	const pwd = () => realpathSync(readFileSync(join(layout.dir, "pwd.txt"), "utf8"));

	const plugin = await ClaudeHooksBridge({
		directory: directoryDir, worktree: worktreeDir, hooksDir: layout.dir, tablePath: layout.tablePath,
	});
	await plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "x" } });
	assert.equal(seenCwd(), realpathSync(worktreeDir));
	assert.equal(pwd(), realpathSync(worktreeDir));
	assert.equal(readFileSync(join(layout.dir, "runtime.txt"), "utf8"), "opencode");

	// bash tool の cwd 引数があればそちら（2026-08-26 push 承認フラグ不一致の再発ガード）
	await plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "x", cwd: toolCwd } });
	assert.equal(seenCwd(), realpathSync(toolCwd));
	assert.equal(pwd(), realpathSync(toolCwd));
});

test("存在しない cwd では spawn error を required hook 失敗として throw し、plugin host を落とさない", async () => {
	const layout = fixtureLayout("ocb-", [{ file: "guard.sh", required: true }]);
	const plugin = await pluginFor(layout);
	await assert.rejects(
		plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "x", cwd: join(layout.dir, "does-not-exist") } }),
		/spawn failed/,
	);
});

test("実 table + 実 hook: grep 直叩きは deny、confirm rule は hook を通し rtk-rewrite が prefix を付ける", async () => {
	const repo = process.cwd();
	const flagDir = mkdtempSync(join(tmpdir(), "ocb-approval-"));
	await withEnv("CODEX_REVIEW_FLAG_DIR", flagDir, async () => {
		const plugin = await ClaudeHooksBridge({
			directory: repo, worktree: repo, hooksDir: REAL_HOOKS_DIR, tablePath: REAL_TABLE_PATH,
		});
		await assert.rejects(
			plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "grep -r foo .", cwd: repo } }),
			/rg/,
		);
		await assert.rejects(
			plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "gh repo delete owner/repo", cwd: repo } }),
			/リポジトリの delete\/edit はユーザーの明示的な許可/,
		);
		// gh pr merge / git push は opencode override で confirm → native permission の
		// ask が所有するため、hook は deny しない（承認スクリプトを案内する message も出ない）
		const passthrough = { args: { command: "gh pr merge 123", cwd: repo } };
		await plugin["tool.execute.before"]({ tool: "bash" }, passthrough);
		assert.match(passthrough.args.command, /gh pr merge 123$/);
	});
});

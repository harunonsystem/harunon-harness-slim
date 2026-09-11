import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PostEditChecks } from "../../../packages/core/opencode-plugins/post-edit-checks.js";
import { REAL_HOOKS_DIR } from "./_fixtures.ts";

// OpenCode adapter: tool.execute.after の filePath 取り出しと output.output への追記だけを見る。

test("壊れた JSON は tool result 末尾に追記され、正しい JSON は触らない", async () => {
	const dir = mkdtempSync(join(tmpdir(), "oc-pec-"));
	const bad = join(dir, "bad.json");
	writeFileSync(bad, "{broken");
	const plugin = await PostEditChecks({ hooksDir: REAL_HOOKS_DIR });
	const output = { output: "wrote file", args: { filePath: bad } };
	await plugin["tool.execute.after"]({ tool: "write" }, output);
	assert.ok(output.output.startsWith("wrote file"));
	assert.ok(output.output.includes("[post-edit-check]"));
	assert.ok(output.output.includes("invalid JSON"));

	const good = join(dir, "good.json");
	writeFileSync(good, '{"a": 1}');
	const clean = { output: "wrote file", args: { filePath: good } };
	await plugin["tool.execute.after"]({ tool: "edit" }, clean);
	assert.equal(clean.output, "wrote file");
});

test("edit / write 以外のツールは無視し、.md は fix-gfm-tables.js の担当なので触らない", async () => {
	const dir = mkdtempSync(join(tmpdir(), "oc-pec-"));
	const plugin = await PostEditChecks({ hooksDir: REAL_HOOKS_DIR });
	const output = { output: "x", args: { filePath: "/nonexistent/bad.json" } };
	await plugin["tool.execute.after"]({ tool: "bash" }, output);
	assert.equal(output.output, "x");

	const md = join(dir, "doc.md");
	writeFileSync(md, "a | b\n--- | ---\n1 | 2\n");
	const mdOutput = { output: "x", args: { filePath: md } };
	await plugin["tool.execute.after"]({ tool: "write" }, mdOutput);
	assert.equal(mdOutput.output, "x");
	assert.equal(readFileSync(md, "utf8").split("\n")[0], "a | b");
});

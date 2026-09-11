import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import postEditChecks, {
	createToolResultHandler,
} from "../../../packages/core/pi-extensions/post-edit-checks.js";
import { REAL_HOOKS_DIR } from "./_fixtures.ts";

// pi / omp 共有 adapter: tool_result の path 取り出しと content 末尾への追記だけを見る。

test("tool_result に登録される", () => {
	const events: string[] = [];
	postEditChecks({ on: (name: string) => events.push(name) });
	assert.deepEqual(events, ["tool_result"]);
});

test("壊れた JSON は content 末尾に追記、isError / 非編集ツール / 正常ファイルは undefined", async () => {
	const handler = createToolResultHandler({ hooksDir: REAL_HOOKS_DIR });
	const dir = mkdtempSync(join(tmpdir(), "pi-pec-"));
	const bad = join(dir, "bad.json");
	writeFileSync(bad, "{broken");
	const base = { toolCallId: "1", content: [{ type: "text", text: "ok" }] };

	const result = await handler({ ...base, toolName: "write", input: { path: bad } });
	assert.equal(result.content.length, 2);
	assert.equal(result.content[0].text, "ok");
	assert.ok(result.content[1].text.includes("[post-edit-check]"));
	assert.ok(result.content[1].text.includes("invalid JSON"));

	assert.equal(await handler({ ...base, toolName: "write", input: { path: bad }, isError: true }), undefined);
	assert.equal(await handler({ ...base, toolName: "bash", input: { command: "ls" } }), undefined);
	assert.equal(await handler({ ...base, toolName: "edit", input: {} }), undefined);
	const good = join(dir, "good.json");
	writeFileSync(good, "{}");
	assert.equal(await handler({ ...base, toolName: "edit", input: { path: good } }), undefined);
});

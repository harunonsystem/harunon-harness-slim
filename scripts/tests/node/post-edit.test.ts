import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkKindFor, postEditFindings } from "../../../packages/core/hook-runner/post-edit.js";
import { REAL_HOOKS_DIR } from "./_fixtures.ts";

// 判定本体は packages/core/hooks/post-edit-checks.sh（test_post_edit_checks.py が契約を持つ）。
// ここでは共有 module の interface（拡張子フィルタ・markdown フラグ・findings の返し方）だけを見る。

const opts = { hooksDir: REAL_HOOKS_DIR };

test("拡張子でチェック種別を選ぶ", () => {
	assert.equal(checkKindFor("a/b.md"), "md");
	assert.equal(checkKindFor("x.sh"), "sh");
	assert.equal(checkKindFor("x.json"), "json");
	assert.equal(checkKindFor("x.jsonc"), "json");
	assert.equal(checkKindFor("x.ts"), undefined);
	assert.equal(checkKindFor(undefined), undefined);
});

test("壊れた JSON は指摘が返り、正しい JSON と対象外の拡張子は返らない", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pec-"));
	const bad = join(dir, "bad.json");
	writeFileSync(bad, "{broken");
	assert.ok((await postEditFindings(bad, opts))?.includes("invalid JSON"));

	const good = join(dir, "good.json");
	writeFileSync(good, '{"a": 1}');
	assert.equal(await postEditFindings(good, opts), undefined);
	assert.equal(await postEditFindings("/nonexistent/a.ts", opts), undefined);
});

test("shellcheck 指摘のある .sh は報告される（未インストールならスキップ仕様で undefined）", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pec-"));
	const sh = join(dir, "bad.sh");
	writeFileSync(sh, "#!/bin/bash\ncd /tmp\nls\n");
	const findings = await postEditFindings(sh, opts);
	if (findings !== undefined) assert.ok(findings.startsWith("shellcheck:"));
});

test(".md は GFM 自動修正のみで指摘を返さず、markdown: false なら触らない", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pec-"));
	const md = join(dir, "doc.md");
	writeFileSync(md, "a | b\n--- | ---\n1 | 2\n");
	assert.equal(await postEditFindings(md, { ...opts, markdown: false }), undefined);
	assert.equal(readFileSync(md, "utf8").split("\n")[0], "a | b");
	assert.equal(await postEditFindings(md, opts), undefined);
	assert.equal(readFileSync(md, "utf8").split("\n")[0], "| a | b |");
});

test("script が無い hooks dir では advisory として undefined を返す", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pec-"));
	const bad = join(dir, "bad.json");
	writeFileSync(bad, "{broken");
	assert.equal(await postEditFindings(bad, { hooksDir: join(dir, "nope") }), undefined);
});

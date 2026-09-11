import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
	apiKeyFrom,
	buildRegisterCalls,
	type ProviderCatalog,
} from "../../../packages/core/pi-extensions/harness-providers.ts";
// @ts-ignore JS モジュール（opencode plugin）
import { buildProviderEntries } from "../../../packages/core/opencode-plugins/model-providers.js";

const CATALOG_PATH = new URL("../../../packages/core/model-providers.json", import.meta.url)
	.pathname;
const catalog = JSON.parse(readFileSync(CATALOG_PATH, "utf8")) as ProviderCatalog;

test("keyRef は opencode auth の !command または env 参照に変換される", () => {
	assert.equal(
		apiKeyFrom({ opencodeAuth: "cerebras" }),
		'!jq -r ".cerebras.key" ~/.local/share/opencode/auth.json',
	);
	assert.equal(apiKeyFrom({ env: "NARAROUTER_API_KEY" }), "$NARAROUTER_API_KEY");
	assert.throws(() => apiKeyFrom({}));
});

test("pi: 実カタログから zen + 組み込み key 上書きが生成される", () => {
	const calls = buildRegisterCalls(catalog);
	const names = calls.map((call) => call.name);
	assert.deepEqual(names, ["opencode-zen", "cerebras", "mistral"]);

	const zen = calls.find((call) => call.name === "opencode-zen");
	assert.equal(zen?.config.baseUrl, "https://opencode.ai/zen/v1");
	const zenModels = zen?.config.models as Array<{ id: string; cost: { input: number } }>;
	assert.ok(zenModels.some((model) => model.id === "big-pickle"));
	assert.equal(zenModels[0].cost.input, 0);

	const cerebras = calls.find((call) => call.name === "cerebras");
	assert.deepEqual(Object.keys(cerebras?.config ?? {}), ["apiKey"]);
});

test("opencode: opencodeNative なプロバイダは注入しない（非 native は現カタログに無い）", () => {
	const entries = buildProviderEntries(catalog);
	assert.deepEqual(Object.keys(entries), []);
});

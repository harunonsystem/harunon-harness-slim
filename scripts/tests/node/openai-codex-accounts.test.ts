import { test } from "node:test";
import assert from "node:assert/strict";
import {
	accountIdFromAccessToken,
	accountStateFromEntries,
	isQuotaErrorMessage,
	isQuotaOrRateLimitResponse,
	parseResetAt,
	parseResetAtFromMessage,
} from "../../../packages/core/pi-extensions/openai-codex-accounts.ts";

test("quota/rate-limit だけが rotation 対象になる", () => {
	assert.equal(isQuotaOrRateLimitResponse(429, {}), true);
	assert.equal(isQuotaOrRateLimitResponse(401, { "retry-after": "1" }), false);
	assert.equal(isQuotaOrRateLimitResponse(403, {}), false);
	assert.equal(isQuotaOrRateLimitResponse(500, {}), false);
	assert.equal(isQuotaOrRateLimitResponse(200, { "x-ratelimit-reset": "10" }), false);
});

test("レスポンス本文の明示的な quota/rate-limit エラーだけを検出する", () => {
	assert.equal(isQuotaErrorMessage("Monthly usage limit reached"), true);
	assert.equal(isQuotaErrorMessage("rate_limit_exceeded"), true);
	assert.equal(isQuotaErrorMessage("authentication failed"), false);
	assert.equal(isQuotaErrorMessage("billing authorization failed"), false);
	assert.equal(isQuotaErrorMessage("network timeout"), false);
	assert.equal(isQuotaErrorMessage("internal server error"), false);
});

test("reset header は retry-after と Unix timestamp を解釈する", () => {
	assert.equal(parseResetAt({ "retry-after": "2" }, 1_000), 3_000);
	assert.equal(parseResetAt({ "x-ratelimit-reset": "1700000000" }, 1_000), 1_700_000_000_000);
	assert.equal(parseResetAt({ "retry-after": "Wed, 21 Oct 2015 07:28:00 GMT" }, 1_000), 1_445_412_480_000);
	assert.equal(parseResetAt({}, 1_000), undefined);
});

test("quota エラーメッセージの報告時刻も work 再試行に使える", () => {
	assert.equal(parseResetAtFromMessage("Try again in ~2 min.", 1_000), 121_000);
	assert.equal(parseResetAtFromMessage("reset at 2026-07-31T12:00:00Z", 1_000), Date.parse("2026-07-31T12:00:00Z"));
	assert.equal(parseResetAtFromMessage("quota exceeded", 1_000), undefined);
});

test("session custom entry から最後の account affinity を復元する", () => {
	assert.deepEqual(
		accountStateFromEntries([
			{ type: "custom", customType: "openai-codex-account", data: { account: "work" } },
			{ type: "message" },
			{ type: "custom", customType: "openai-codex-account", data: { account: "personal", reason: "quota/rate-limit" } },
		]),
		{ account: "personal", reason: "quota/rate-limit", status: undefined, resetAt: undefined },
	);
	assert.equal(accountStateFromEntries([{ type: "custom", customType: "other", data: { account: "personal" } }]), undefined);
});

test("JWT の account id は表示用に抽出できるが token 自体は返さない", () => {
	const payload = Buffer.from(JSON.stringify({ "https://api.openai.com/auth": { chatgpt_account_id: "acct-work" } })).toString("base64url");
	assert.equal(accountIdFromAccessToken(`header.${payload}.signature`), "acct-work");
	assert.equal(accountIdFromAccessToken("not-a-jwt"), undefined);
});

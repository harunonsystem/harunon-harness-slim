#!/usr/bin/env node

// Pi resolves `!command` API keys through this helper. It deliberately emits
// only the access token on stdout; diagnostics never include OAuth material.
import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const account = process.argv[2];
if (account !== "work" && account !== "personal") process.exit(2);

const configDir = join(homedir(), ".pi", "agent");
const accountsPath = join(configDir, "openai-codex-accounts.json");
const authPath = join(configDir, "auth.json");
const clientId = "app_EMoamEEZ73f0CkXaXp7hrann";
const tokenUrl = "https://auth.openai.com/oauth/token";

function readJson(path) {
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return undefined;
	}
}

function credential(value) {
	if (!value || typeof value !== "object" || typeof value.access !== "string" || !value.access) return undefined;
	return {
		access: value.access,
		refresh: typeof value.refresh === "string" ? value.refresh : undefined,
		expires: typeof value.expires === "number" ? value.expires : undefined,
	};
}

const accounts = readJson(accountsPath);
let current = credential(accounts?.[account]);
if (!current && account === "work") current = credential(readJson(authPath)?.["openai-codex"]);
if (!current) process.exit(3);

async function refresh(value) {
	if (!value.refresh || (value.expires && value.expires > Date.now() + 60_000)) return value;
	const response = await fetch(tokenUrl, {
		method: "POST",
		headers: { "content-type": "application/x-www-form-urlencoded" },
		body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: value.refresh, client_id: clientId }),
	});
	if (!response.ok) process.exit(4);
	const body = await response.json();
	if (typeof body?.access_token !== "string" || typeof body?.expires_in !== "number") process.exit(5);
	const next = {
		access: body.access_token,
		refresh: typeof body.refresh_token === "string" ? body.refresh_token : value.refresh,
		expires: Date.now() + body.expires_in * 1000,
	};
	if (accounts && typeof accounts === "object" && !Array.isArray(accounts)) {
		accounts[account] = { type: "oauth", ...next };
		mkdirSync(configDir, { recursive: true, mode: 0o700 });
		const temporary = `${accountsPath}.${process.pid}.tmp`;
		writeFileSync(temporary, `${JSON.stringify(accounts, null, 2)}\n`, { mode: 0o600 });
		chmodSync(temporary, 0o600);
		renameSync(temporary, accountsPath);
	} else if (account === "work") {
		const auth = readJson(authPath);
		if (auth && typeof auth === "object" && !Array.isArray(auth)) {
			auth["openai-codex"] = { type: "oauth", ...next };
			const temporary = `${authPath}.${process.pid}.tmp`;
			writeFileSync(temporary, `${JSON.stringify(auth, null, 2)}\n`, { mode: 0o600 });
			chmodSync(temporary, 0o600);
			renameSync(temporary, authPath);
		}
	}
	return next;
}

try {
	const active = await refresh(current);
	process.stdout.write(active.access);
} catch {
	process.exit(6);
}

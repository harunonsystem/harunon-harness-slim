/**
 * Session-scoped account rotation for the built-in openai-codex provider.
 *
 * OAuth credentials are intentionally kept outside the repository, under
 * ~/.pi/agent. The session only stores the non-secret account name and the
 * reason for a switch, so resumed sessions keep their account affinity.
 */
import {
	appendFileSync,
	chmodSync,
	existsSync,
	mkdirSync,
	readFileSync,
	renameSync,
	writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { AssistantMessage, AssistantMessageEvent } from "@earendil-works/pi-ai";
import { createJapanesePolisher, japaneseOutputSessions, JAPANESE_REWRITE_CONTRACT } from "../hook-runner/japanese-output.js";
import { withCredentialLock } from "./lib/credential-lock.mjs";
import type {
	ExtensionAPI,
	ExtensionContext,
	ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";

export const CODEX_PROVIDER = "openai-codex";
export const ACCOUNT_ENTRY_TYPE = "openai-codex-account";
export const ACCOUNTS_FILE = "openai-codex-accounts.json";
export const ACCOUNT_SETTINGS_FILE = "openai-codex-account-settings.json";
export const ACCOUNT_LOG_FILE = "openai-codex-account-rotation.log";
export const ACCOUNT_NAMES = ["work", "personal"] as const;
export type AccountName = (typeof ACCOUNT_NAMES)[number];

const REFRESH_SKEW_MS = 60_000;
const MAX_TIMER_DELAY_MS = 2_147_000_000;
const TOKEN_URL = "https://auth.openai.com/oauth/token";
const CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann";

export interface AccountCredential {
	access: string;
	refresh?: string;
	expires?: number;
}

export interface AccountEntryData {
	account: AccountName;
	reason?: string;
	status?: number;
	resetAt?: number;
}

export interface AccountSettings {
	manualOverride?: AccountName;
}

interface AccountState extends AccountEntryData {}

function configDir(): string {
	return join(homedir(), ".pi", "agent");
}

function configPath(file: string): string {
	return join(configDir(), file);
}

function isAccountName(value: unknown): value is AccountName {
	return value === "work" || value === "personal";
}

function readJson(path: string): unknown {
	try {
		return JSON.parse(readFileSync(path, "utf8")) as unknown;
	} catch {
		return undefined;
	}
}

function writePrivateJson(path: string, value: unknown): void {
	const dir = join(path, "..");
	mkdirSync(dir, { recursive: true, mode: 0o700 });
	const temporary = `${path}.${process.pid}.tmp`;
	writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
	chmodSync(temporary, 0o600);
	renameSync(temporary, path);
}

function readSettings(): AccountSettings {
	const value = readJson(configPath(ACCOUNT_SETTINGS_FILE));
	if (!value || typeof value !== "object" || Array.isArray(value)) return {};
	const manualOverride = (value as Record<string, unknown>).manualOverride;
	return isAccountName(manualOverride) ? { manualOverride } : {};
}

function saveSettings(settings: AccountSettings): void {
	writePrivateJson(configPath(ACCOUNT_SETTINGS_FILE), settings);
}

function asCredential(value: unknown): AccountCredential | undefined {
	if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
	const record = value as Record<string, unknown>;
	if (typeof record.access !== "string" || !record.access) return undefined;
	return {
		access: record.access,
		refresh: typeof record.refresh === "string" ? record.refresh : undefined,
		expires: typeof record.expires === "number" ? record.expires : undefined,
	};
}

function readAccounts(): Record<string, unknown> {
	const value = readJson(configPath(ACCOUNTS_FILE));
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

/** Reads an account without returning credentials in status/UI paths. */
export function readAccountCredential(account: AccountName): AccountCredential | undefined {
	const configured = asCredential(readAccounts()[account]);
	if (configured) return configured;

	// A freshly installed setup already has the primary OAuth credential in
	// auth.json. Treat it as work until the user imports separate accounts.
	if (account !== "work") return undefined;
	const auth = readJson(configPath("auth.json"));
	if (!auth || typeof auth !== "object" || Array.isArray(auth)) return undefined;
	return asCredential((auth as Record<string, unknown>)[CODEX_PROVIDER]);
}

function writeAccounts(accounts: Record<string, unknown>): void {
	writePrivateJson(configPath(ACCOUNTS_FILE), accounts);
}

function clearTransientAuthCredential(): void {
	const authPath = configPath("auth.json");
	const auth = readJson(authPath);
	if (!auth || typeof auth !== "object" || Array.isArray(auth)) return;
	if (!(CODEX_PROVIDER in auth)) return;
	delete (auth as Record<string, unknown>)[CODEX_PROVIDER];
	writePrivateJson(authPath, auth);
}

export async function importCurrentCodexCredential(account: AccountName): Promise<boolean> {
	return withCredentialLock(configDir(), () => {
		const auth = readJson(configPath("auth.json"));
		if (!auth || typeof auth !== "object" || Array.isArray(auth)) return false;
		const credential = asCredential((auth as Record<string, unknown>)[CODEX_PROVIDER]);
		if (!credential) return false;
		const accounts = readAccounts();
		accounts[account] = { type: "oauth", ...credential };
		writeAccounts(accounts);
		// Once work is in the account store, avoid letting Pi's single built-in auth
		// slot select an unrelated account before streamSimple runs.
		if (asCredential(accounts.work)) clearTransientAuthCredential();
		return true;
	});
}

function updateAccountCredential(account: AccountName, credential: AccountCredential): void {
	const accounts = readAccounts();
	accounts[account] = { type: "oauth", ...credential };
	writeAccounts(accounts);
}

function decodeJwtPayload(token: string): Record<string, unknown> | undefined {
	try {
		const payload = token.split(".")[1];
		if (!payload) return undefined;
		return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<string, unknown>;
	} catch {
		return undefined;
	}
}

export function accountIdFromAccessToken(token: string): string | undefined {
	const payload = decodeJwtPayload(token);
	const auth = payload?.["https://api.openai.com/auth"];
	if (!auth || typeof auth !== "object" || Array.isArray(auth)) return undefined;
	const accountId = (auth as Record<string, unknown>).chatgpt_account_id;
	return typeof accountId === "string" && accountId ? accountId : undefined;
}

async function refreshCredential(credential: AccountCredential): Promise<AccountCredential> {
	if (!credential.refresh) return credential;
	const response = await fetch(TOKEN_URL, {
		signal: AbortSignal.timeout(20_000),
		method: "POST",
		headers: { "content-type": "application/x-www-form-urlencoded" },
		body: new URLSearchParams({
			grant_type: "refresh_token",
			refresh_token: credential.refresh,
			client_id: CLIENT_ID,
		}),
	});
	if (!response.ok) throw new Error(`OAuth refresh failed (${response.status})`);
	const value = (await response.json()) as Record<string, unknown>;
	if (typeof value.access_token !== "string" || typeof value.expires_in !== "number") {
		throw new Error("OAuth refresh response is missing required fields");
	}
	return {
		access: value.access_token,
		refresh: typeof value.refresh_token === "string" ? value.refresh_token : credential.refresh,
		expires: Date.now() + value.expires_in * 1000,
	};
}

async function accessTokenFor(account: AccountName): Promise<string | undefined> {
	return withCredentialLock(configDir(), async () => {
		const credential = readAccountCredential(account);
		if (!credential) return undefined;
		if (!credential.expires || credential.expires > Date.now() + REFRESH_SKEW_MS) {
			return credential.access;
		}
		const refreshed = await refreshCredential(credential);
		if (account === "work" && !readAccounts()[account]) {
			// Keep the built-in provider's normal auth storage in sync when work has
			// not yet been imported into the account file.
			const authPath = configPath("auth.json");
			const auth = readJson(authPath);
			if (auth && typeof auth === "object" && !Array.isArray(auth)) {
				(auth as Record<string, unknown>)[CODEX_PROVIDER] = { type: "oauth", ...refreshed };
				writePrivateJson(authPath, auth);
			}
		} else {
			updateAccountCredential(account, refreshed);
		}
		return refreshed.access;
	});
}

function headerValue(headers: Record<string, string>, name: string): string | undefined {
	const wanted = name.toLowerCase();
	for (const [key, value] of Object.entries(headers)) {
		if (key.toLowerCase() === wanted) return value;
	}
	return undefined;
}

export function parseResetAt(headers: Record<string, string>, now = Date.now()): number | undefined {
	const retryAfterMs = headerValue(headers, "retry-after-ms");
	if (retryAfterMs !== undefined && /^\d+(?:\.\d+)?$/.test(retryAfterMs.trim())) {
		return now + Math.max(0, Number(retryAfterMs));
	}
	const retryAfter = headerValue(headers, "retry-after");
	if (retryAfter !== undefined) {
		if (/^\d+(?:\.\d+)?$/.test(retryAfter.trim())) return now + Math.max(0, Number(retryAfter) * 1000);
		const date = Date.parse(retryAfter);
		if (!Number.isNaN(date)) return Math.max(now, date);
	}
	for (const name of ["x-ratelimit-reset", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "x-reset-time"]) {
		const value = headerValue(headers, name);
		if (!value) continue;
		const seconds = Number(value);
		if (Number.isFinite(seconds)) {
			// Unix timestamps are currently around 1e9; durations are much smaller.
			return seconds > 100_000_000 ? seconds * 1000 : now + Math.max(0, seconds * 1000);
		}
		const date = Date.parse(value);
		if (!Number.isNaN(date)) return Math.max(now, date);
	}
	return undefined;
}

export function isQuotaOrRateLimitResponse(status: number, _headers: Record<string, string>): boolean {
	// Do not infer rotation from a header on an auth, policy, or server error.
	// HTTP 429 is the explicit provider-level rate-limit response.
	return status === 429;
}

export function isQuotaErrorMessage(message: string): boolean {
	return /(?:GoUsageLimitError|FreeUsageLimitError|Monthly usage limit reached|usage[_ ]limit(?: reached)?|usage_not_included|available balance|insufficient_quota|out of budget|quota exceeded|(?:quota|usage) billing|rate[_ ]limit(?:_exceeded)?|too many requests)/i.test(message);
}

export function parseResetAtFromMessage(message: string, now = Date.now()): number | undefined {
	const date = message.match(/(?:reset|retry|try again)(?: at| on)\s+((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+[^.]+|\d{4}-\d{2}-\d{2}T[^\s.]+)/i);
	if (date) {
		const parsed = Date.parse(date[1]);
		if (!Number.isNaN(parsed)) return Math.max(now, parsed);
	}
	const minutes = message.match(/(?:try again in|resets? in)\s+~?\s*(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)/i);
	if (minutes) return now + Math.max(0, Number(minutes[1]) * 60_000);
	const seconds = message.match(/(?:try again in|resets? in)\s+~?\s*(\d+(?:\.\d+)?)\s*(?:seconds?|secs?)/i);
	if (seconds) return now + Math.max(0, Number(seconds[1]) * 1_000);
	return undefined;
}

function latestEntry(entries: unknown[]): AccountState | undefined {
	for (let index = entries.length - 1; index >= 0; index--) {
		const entry = entries[index];
		if (!entry || typeof entry !== "object") continue;
		const record = entry as Record<string, unknown>;
		if (record.type !== "custom" || record.customType !== ACCOUNT_ENTRY_TYPE) continue;
		const data = record.data;
		if (!data || typeof data !== "object" || Array.isArray(data)) continue;
		const account = (data as Record<string, unknown>).account;
		if (isAccountName(account)) {
			return {
				account,
				reason: typeof (data as Record<string, unknown>).reason === "string" ? (data as Record<string, unknown>).reason as string : undefined,
				status: typeof (data as Record<string, unknown>).status === "number" ? (data as Record<string, unknown>).status as number : undefined,
				resetAt: typeof (data as Record<string, unknown>).resetAt === "number" ? (data as Record<string, unknown>).resetAt as number : undefined,
			};
		}
	}
	return undefined;
}

export function accountStateFromEntries(entries: unknown[]): AccountState | undefined {
	return latestEntry(entries);
}

/**
 * The provider callback must return a stream synchronously, while account
 * refresh and the pi-ai module load are asynchronous. This small forwarding
 * stream keeps that contract without importing pi-ai at extension load time.
 */
function createForwardingStream<T>(model: { api: string; provider: string; id: string }, setup: () => Promise<AsyncIterable<T>>, onEvent?: (event: T) => void): any {
	const queue: T[] = [];
	const waiters: Array<(result: IteratorResult<T>) => void> = [];
	let finished = false;
	let finalResult: unknown;
	let resolveResult!: (result: unknown) => void;
	const resultPromise = new Promise<unknown>((resolve) => {
		resolveResult = resolve;
	});

	function push(value: T): void {
		const waiter = waiters.shift();
		if (waiter) waiter({ value, done: false });
		else queue.push(value);
	}

	function finish(result?: unknown): void {
		if (finished) return;
		finished = true;
		finalResult = result;
		for (const waiter of waiters.splice(0)) waiter({ value: undefined as T, done: true });
		resolveResult(finalResult);
	}

	void setup().then(async (source) => {
		for await (const event of source) {
			onEvent?.(event);
			push(event);
		}
		finish("result" in source && typeof source.result === "function"
			? await source.result()
			: undefined);
	}).catch((error: unknown) => {
		const message = {
			role: "assistant",
			content: [],
			api: model.api,
			provider: model.provider,
			model: model.id,
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			stopReason: "error",
			errorMessage: error instanceof Error ? error.message : String(error),
			timestamp: Date.now(),
		};
		push({ type: "error", reason: "error", error: message } as T);
		finish(message);
	});

	return {
		[Symbol.asyncIterator]() {
			return {
				next: (): Promise<IteratorResult<T>> => {
					if (queue.length > 0) return Promise.resolve({ value: queue.shift()!, done: false });
					if (finished) return Promise.resolve({ value: undefined as T, done: true });
					return new Promise<IteratorResult<T>>((resolve) => waiters.push(resolve));
				},
			};
		},
		result: () => resultPromise,
	};
}

type Polish = (texts: string[], signal?: AbortSignal) => Promise<string[]>;

/** Buffer before display; reconstruct protocol events and keep tool/thinking blocks intact. */
export function polishedStream(source: AsyncIterable<AssistantMessageEvent>, polish: Polish, signal?: AbortSignal) {
	let result: AssistantMessage | undefined;
	const events = (async function* () {
		for await (const event of source) {
			if (event.type === "start") {
				yield { ...event, partial: { ...event.partial, content: [] } };
			} else if (event.type === "error") {
				result = event.error;
				yield event;
			} else if (event.type === "done") {
				const original = event.message;
				const texts = original.content.filter((part) => part.type === "text").map((part) => part.text);
				const replacements = signal?.aborted ? texts : await polish(texts, signal);
				if (signal?.aborted) {
					result = { ...original, stopReason: "aborted" };
					yield { type: "error", reason: "aborted", error: result } satisfies AssistantMessageEvent;
					return;
				}
				let index = 0;
				let changed = false;
				const content = original.content.map((part) => {
					if (part.type !== "text") return part;
					const text = replacements[index++];
					if (text === part.text) return part;
					changed = true;
					const { textSignature: _signature, ...rest } = part;
					return { ...rest, text };
				});
				result = { ...original, content };
				if (changed) delete result.responseId;
				for (let contentIndex = 0; contentIndex < content.length; contentIndex++) {
					const part = content[contentIndex];
					const partial = { ...result, content: content.slice(0, contentIndex + 1) };
					if (part.type === "text") {
						yield { type: "text_start", contentIndex, partial } satisfies AssistantMessageEvent;
						yield { type: "text_delta", contentIndex, delta: part.text, partial } satisfies AssistantMessageEvent;
						yield { type: "text_end", contentIndex, content: part.text, partial } satisfies AssistantMessageEvent;
					} else if (part.type === "thinking") {
						yield { type: "thinking_start", contentIndex, partial } satisfies AssistantMessageEvent;
						yield { type: "thinking_delta", contentIndex, delta: part.thinking, partial } satisfies AssistantMessageEvent;
						yield { type: "thinking_end", contentIndex, content: part.thinking, partial } satisfies AssistantMessageEvent;
					} else {
						yield { type: "toolcall_start", contentIndex, partial } satisfies AssistantMessageEvent;
						yield { type: "toolcall_delta", contentIndex, delta: JSON.stringify(part.arguments), partial } satisfies AssistantMessageEvent;
						yield { type: "toolcall_end", contentIndex, toolCall: part, partial } satisfies AssistantMessageEvent;
					}
				}
				yield { ...event, message: result };
			} // Deltas are held until the complete message has been polished.
		}
	})();
	return Object.assign(events, { result: async () => result });
}

function formatResetAt(resetAt: number | undefined): string {
	return resetAt ? `; work retry ${new Date(resetAt).toISOString()}` : "";
}

function statusText(state: AccountState): string {
	return `account ${state.account}${state.reason ? ` (${state.reason})` : ""}${formatResetAt(state.resetAt)}`;
}

function logSwitch(ctx: ExtensionContext, from: AccountName, to: AccountName, reason: string, status: number, resetAt?: number): void {
	const line = JSON.stringify({
		timestamp: new Date().toISOString(),
		session: ctx.sessionManager.getSessionId(),
		from,
		to,
		reason,
		status,
		...(resetAt ? { resetAt: new Date(resetAt).toISOString() } : {}),
	});
	mkdirSync(configDir(), { recursive: true, mode: 0o700 });
	const logPath = configPath(ACCOUNT_LOG_FILE);
	appendFileSync(logPath, `${line}\n`, { mode: 0o600 });
	chmodSync(logPath, 0o600);
}

function accountForSession(ctx: ExtensionContext): AccountState {
	const override = readSettings().manualOverride;
	const existing = latestEntry(ctx.sessionManager.getEntries() as unknown[]);
	return { account: override ?? existing?.account ?? "work", reason: existing?.reason, resetAt: existing?.resetAt };
}

function setSessionAccount(pi: ExtensionAPI, ctx: ExtensionContext, state: AccountState): void {
	pi.appendEntry(ACCOUNT_ENTRY_TYPE, state);
	ctx.ui.setStatus("openai-codex-account", statusText(state));
}

function notifySwitch(ctx: ExtensionContext, from: AccountName, to: AccountName, resetAt?: number): void {
	const retry = resetAt ? `; retry work at ${new Date(resetAt).toLocaleString()}` : "";
	ctx.ui.notify(`openai-codex account: ${from} → ${to} (quota/rate limit)${retry}`, "warning");
}

function registerAccountCommand(pi: ExtensionAPI, currentState: Map<string, AccountState>): void {
	pi.registerCommand("codex-account", {
		description: "Inspect or override openai-codex work/personal account rotation",
		getArgumentCompletions: () => ACCOUNT_NAMES.map((name) => ({ value: name, label: name })),
		handler: async (args: string, ctx: ExtensionCommandContext) => {
			const [command = "status", value] = args.trim().split(/\s+/, 2);
			const sessionId = ctx.sessionManager.getSessionId();
			const current = currentState.get(sessionId) ?? accountForSession(ctx);
			if (command === "status") {
				const settings = readSettings();
				const availability = ACCOUNT_NAMES.map((name) => `${name}:${readAccountCredential(name) ? "configured" : "missing"}`).join(", ");
				ctx.ui.notify(`${statusText(current)}; override ${settings.manualOverride ?? "auto"}; ${availability}`, "info");
				return;
			}
			if (command === "import" && isAccountName(value)) {
				ctx.ui.notify((await importCurrentCodexCredential(value)) ? `Imported current OAuth credential as ${value}` : "No openai-codex OAuth credential found in auth.json", "info");
				return;
			}
			if (command === "use" && isAccountName(value)) {
				if (!readAccountCredential(value)) {
					ctx.ui.notify(`${value} account is not configured; run /login then /codex-account import ${value}`, "error");
					return;
				}
				saveSettings({ manualOverride: value });
				const next = { account: value, reason: "manual override" } satisfies AccountState;
				currentState.set(sessionId, next);
				setSessionAccount(pi, ctx, next);
				if (current.account !== value) logSwitch(ctx, current.account, value, "manual override", 0);
				ctx.ui.notify(`openai-codex account override: ${value}`, "info");
				return;
			}
			if (command === "auto") {
				saveSettings({});
				ctx.ui.notify("openai-codex account override cleared; new sessions prefer work", "info");
				return;
			}
			ctx.ui.notify("Usage: /codex-account [status|import work|import personal|use work|use personal|auto]", "error");
		},
	});
}

export default function openAICodexAccounts(pi: ExtensionAPI): void {
	const currentState = new Map<string, AccountState>();
	const retryTimers = new Map<string, ReturnType<typeof setTimeout>>();
	const sessionContexts = new Map<string, ExtensionContext>();

	const scheduleWorkRetry = (ctx: ExtensionContext, resetAt: number): void => {
		const sessionId = ctx.sessionManager.getSessionId();
		const existingTimer = retryTimers.get(sessionId);
		if (existingTimer) clearTimeout(existingTimer);
		const retryWork = (): void => {
			if (readSettings().manualOverride) {
				retryTimers.delete(sessionId);
				return;
			}
			const active = currentState.get(sessionId);
			if (!active || active.account !== "personal") {
				retryTimers.delete(sessionId);
				return;
			}
			const remaining = resetAt - Date.now();
			if (remaining > 0) {
				retryTimers.set(sessionId, setTimeout(retryWork, Math.min(remaining, MAX_TIMER_DELAY_MS)));
				return;
			}
			const work = { account: "work", reason: "reported reset elapsed" } satisfies AccountState;
			currentState.set(sessionId, work);
			setSessionAccount(pi, ctx, work);
			logSwitch(ctx, "personal", "work", "reported reset elapsed", active.status ?? 0, resetAt);
			ctx.ui.notify("openai-codex account: personal → work (reported reset elapsed)", "info");
			retryTimers.delete(sessionId);
		};
		retryTimers.set(sessionId, setTimeout(retryWork, Math.max(0, Math.min(resetAt - Date.now(), MAX_TIMER_DELAY_MS))));
	};

	const rotateToPersonal = (ctx: ExtensionContext, status: number, resetAt?: number): void => {
		const sessionId = ctx.sessionManager.getSessionId();
		const current = currentState.get(sessionId) ?? accountForSession(ctx);
		if (current.account !== "work" || readSettings().manualOverride) return;
		const next = { account: "personal", reason: "quota/rate-limit", status, resetAt } satisfies AccountState;
		currentState.set(sessionId, next);
		setSessionAccount(pi, ctx, next);
		logSwitch(ctx, "work", "personal", "quota/rate-limit", status, resetAt);
		notifySwitch(ctx, "work", "personal", resetAt);

		const existingTimer = retryTimers.get(sessionId);
		if (existingTimer) clearTimeout(existingTimer);
		if (resetAt) scheduleWorkRetry(ctx, resetAt);
	};

	// Keep the provider ID and built-in model catalog intact. The command value
	// is resolved by Pi from the user's private config directory and never puts
	// an OAuth token in this repository or in the session log.
	pi.registerProvider(CODEX_PROVIDER, {
		api: "openai-codex-responses",
		apiKey: "!node ~/.pi/agent/extensions/openai-codex-account-token.mjs work",
		streamSimple: (model, context, options) => {
			let responseStatus: number | undefined;
			return createForwardingStream(
				model,
				async () => {
					const sessionId = options?.sessionId;
					const state = sessionId ? currentState.get(sessionId) : undefined;
					const account = state?.account ?? "work";
					const token = await accessTokenFor(account);
					if (!token) throw new Error(`openai-codex ${account} account is not configured`);
					if (model.api !== "openai-codex-responses") throw Error("unexpected Codex API");
					const codexModel = { ...model, api: model.api };
					// Pi's extension loader aliases the SDK root to compat. The native factory
					// also avoids dispatching this request back through the registered adapter.
					const piAi = await import("@earendil-works/pi-ai/compat");
					const policy = sessionId ? japaneseOutputSessions.get(sessionId) : undefined;
					// A Codex WebSocket is cached by session ID. Force the fallback account
					// through SSE so a work-account socket cannot be reused after rotation.
					const source = piAi.openAICodexResponsesApi().streamSimple(codexModel, piAi.normalizeContext(context), {
						...options,
						...(account === "personal" || (policy && !policy.bypass) ? { transport: "sse" as const } : {}),
						apiKey: token,
						onResponse: async (response, responseModel) => {
							responseStatus = response.status;
							await options?.onResponse?.(response, responseModel);
						},
					});
					return policy && !policy.bypass ? polishedStream(source, policy.polish, options?.signal) : source;
				},
				(event) => {
					const record = event as {
						type?: string;
						error?: { errorMessage?: unknown };
					};
					if (record.type !== "error" || typeof record.error?.errorMessage !== "string") return;
					if (responseStatus !== undefined && responseStatus !== 200 && responseStatus !== 429) return;
					if (!isQuotaErrorMessage(record.error.errorMessage)) return;
					const sessionId = options?.sessionId;
					const sessionCtx = sessionId ? sessionContexts.get(sessionId) : undefined;
					if (sessionCtx) rotateToPersonal(sessionCtx, 429, parseResetAtFromMessage(record.error.errorMessage));
				},
			);
		},
	});

	registerAccountCommand(pi, currentState);
	pi.registerCommand("yomiyasu", {
		description: "Session Japanese polishing: on, off, status",
		handler: async (args, ctx) => {
			const policy = japaneseOutputSessions.get(ctx.sessionManager.getSessionId());
			if (!policy) { ctx.ui.notify("yomiyasu: 設定またはモデルを読み込めませんでした。", "warning"); return; }
			if (args.trim() === "off") policy.disabled = true;
			else if (args.trim() === "on") policy.disabled = false;
			else if (args.trim() && args.trim() !== "status") { ctx.ui.notify("Usage: /yomiyasu [on|off|status]", "error"); return; }
			policy.bypass = policy.disabled;
			ctx.ui.notify(`yomiyasu: ${policy.disabled ? "off" : "on"}`, "info");
		},
	});
	pi.on("input", (event, ctx) => {
		const policy = japaneseOutputSessions.get(ctx.sessionManager.getSessionId());
		if (policy) policy.bypass = policy.disabled || /\braw\b|そのまま|逐語|推敲しない/i.test(event.text);
	});

	let previousSessionId: string | undefined;
	const initializeSession = async (ctx: ExtensionContext) => {
		const sessionId = ctx.sessionManager.getSessionId();
		ctx.ui.setStatus("yomiyasu", undefined);
		japaneseOutputSessions.delete(sessionId);
		if (previousSessionId) japaneseOutputSessions.delete(previousSessionId);
		if (previousSessionId && previousSessionId !== sessionId) {
			clearTimeout(retryTimers.get(previousSessionId));
			retryTimers.delete(previousSessionId);
			sessionContexts.delete(previousSessionId);
			currentState.delete(previousSessionId);
		}
		previousSessionId = sessionId;
		sessionContexts.set(sessionId, ctx);
		const path = join(process.env.PI_CODING_AGENT_DIR ?? configDir(), "japanese-output.json");
		if (existsSync(path)) {
			try {
				const config: unknown = JSON.parse(readFileSync(path, "utf8"));
				if (!config || typeof config !== "object" || Array.isArray(config) ||
					!("enabled" in config) || typeof config.enabled !== "boolean" ||
					!("provider" in config) || config.provider !== CODEX_PROVIDER ||
					!("model" in config) || !("thinking" in config) || !("timeoutMs" in config) || !("maxChars" in config) ||
					typeof config.model !== "string" ||
					(config.thinking !== "low" && config.thinking !== "medium" && config.thinking !== "high" && config.thinking !== "xhigh") ||
					typeof config.timeoutMs !== "number" || !Number.isInteger(config.timeoutMs) || config.timeoutMs < 1 || config.timeoutMs > 60000 ||
					typeof config.maxChars !== "number" || !Number.isInteger(config.maxChars) || config.maxChars < 1 || config.maxChars > 24000) throw Error("invalid config");
				const model = ctx.modelRegistry.find(config.provider, config.model);
				if (!model || model.api !== "openai-codex-responses") throw Error("missing Codex model");
				const codexModel = { ...model, api: model.api };
				const reasoning = config.thinking;
				const skillDir = join(homedir(), ".agents", "skills", "yomiyasu");
				const instructions = ["SKILL.md", "references/domains/tech.md"].map((file) => readFileSync(join(skillDir, file), "utf8")).join("\n");
				const polish: Polish = createJapanesePolisher({
					instructions, timeoutMs: config.timeoutMs, maxChars: config.maxChars,
					complete: async ({ instructions, documents, slots, signal }) => {
						const account = currentState.get(sessionId)?.account ?? "work";
						const apiKey = await accessTokenFor(account);
						if (!apiKey) throw Error("missing credential");
						const piAi = await import("@earendil-works/pi-ai/compat");
						if (signal.aborted || japaneseOutputSessions.get(sessionId)?.polish !== polish) throw Error("aborted");
						ctx.ui.setStatus("yomiyasu", "yomiyasu: 推敲中");
						const response = await piAi.openAICodexResponsesApi().streamSimple(codexModel, piAi.normalizeContext({
							messages: [
								{ role: "system", timestamp: Date.now(), content: `${instructions}\n${JAPANESE_REWRITE_CONTRACT}` },
								{ role: "user", timestamp: Date.now(), content: JSON.stringify({ documents, slots }) },
							],
						}), { apiKey, reasoning, transport: "sse", signal }).result();
						if (japaneseOutputSessions.get(sessionId)?.polish !== polish) throw Error("inactive session");
						pi.appendEntry("japanese-output-usage", { model: model.id, usage: response.usage });
						if (response.stopReason === "error" || response.stopReason === "aborted") throw Error("provider error");
						return response.content.filter((part) => part.type === "text").map((part) => part.text).join("");
					},
					report: (report) => {
						if (japaneseOutputSessions.get(sessionId)?.polish !== polish) return;
						ctx.ui.setStatus("yomiyasu", undefined);
						pi.appendEntry("japanese-output", report);
						if (report.outcome === "fallback") ctx.ui.notify(`yomiyasu: ${report.reason} のため原文を残しました。`, "warning");
					},
				});
				japaneseOutputSessions.set(sessionId, { polish, disabled: !config.enabled, bypass: !config.enabled });
			} catch {
				ctx.ui.notify("yomiyasu: 設定・モデル・skill を読み込めないため推敲を無効にしました。", "warning");
			}
		}
		const state = accountForSession(ctx);
		currentState.set(sessionId, state);
		if (state.account === "personal" && state.resetAt) scheduleWorkRetry(ctx, state.resetAt);
		if (!latestEntry(ctx.sessionManager.getEntries() as unknown[])) setSessionAccount(pi, ctx, state);
		else ctx.ui.setStatus("openai-codex-account", statusText(state));
	};
	pi.on("session_start", (_event, ctx) => initializeSession(ctx));

	pi.on("after_provider_response", async (event, ctx) => {
		if (ctx.model?.provider !== CODEX_PROVIDER || !isQuotaOrRateLimitResponse(event.status, event.headers)) return;
		rotateToPersonal(ctx, event.status, parseResetAt(event.headers));
	});

	pi.on("session_shutdown", async (_event, ctx) => {
		const sessionId = ctx.sessionManager.getSessionId();
		const timer = retryTimers.get(sessionId);
		if (timer) clearTimeout(timer);
		retryTimers.delete(sessionId);
		currentState.delete(sessionId);
		sessionContexts.delete(sessionId);
		japaneseOutputSessions.delete(sessionId);
	});
}

/**
 * harness 管理のモデルプロバイダを pi に登録する。
 * 定義の SSOT は model-providers.json（配布コピーを実行時に読む）。
 * key はコピーせず、opencode auth.json への !command 参照 / env 参照に変換する。
 * SSOT: harunon-harness packages/core/{model-providers.json,pi-extensions/}
 */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const OPENCODE_AUTH = "~/.local/share/opencode/auth.json";

export interface KeyRef {
	opencodeAuth?: string;
	env?: string;
}

export interface CatalogModel {
	id: string;
	name: string;
	reasoning: boolean;
	contextWindow: number;
	maxTokens: number;
}

export interface CustomProviderDef {
	displayName: string;
	baseUrl: string;
	piApi: string;
	keyRef: KeyRef;
	models: CatalogModel[];
}

export interface ProviderCatalog {
	customProviders?: Record<string, CustomProviderDef>;
	builtinKeyRefs?: Record<string, KeyRef>;
}

export function apiKeyFrom(keyRef: KeyRef): string {
	if (keyRef.opencodeAuth) {
		return `!jq -r ".${keyRef.opencodeAuth}.key" ${OPENCODE_AUTH}`;
	}
	if (keyRef.env) {
		return `$${keyRef.env}`;
	}
	throw new Error("keyRef must specify opencodeAuth or env");
}

export interface RegisterCall {
	name: string;
	config: Record<string, unknown>;
}

export function buildRegisterCalls(catalog: ProviderCatalog): RegisterCall[] {
	const calls: RegisterCall[] = [];
	for (const [name, def] of Object.entries(catalog.customProviders ?? {})) {
		calls.push({
			name,
			config: {
				name: def.displayName,
				api: def.piApi,
				baseUrl: def.baseUrl,
				apiKey: apiKeyFrom(def.keyRef),
				models: def.models.map((model) => ({
					...model,
					input: ["text"],
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				})),
			},
		});
	}
	for (const [name, keyRef] of Object.entries(catalog.builtinKeyRefs ?? {})) {
		calls.push({ name, config: { apiKey: apiKeyFrom(keyRef) } });
	}
	return calls;
}

const CATALOG_PATH = join(homedir(), ".pi", "agent", "model-providers.json");

export default function harnessProviders(pi: ExtensionAPI) {
	if (!existsSync(CATALOG_PATH)) {
		return;
	}
	const catalog = JSON.parse(readFileSync(CATALOG_PATH, "utf8")) as ProviderCatalog;
	for (const call of buildRegisterCalls(catalog)) {
		pi.registerProvider(call.name, call.config as Parameters<ExtensionAPI["registerProvider"]>[1]);
	}
}

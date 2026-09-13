/**
 * harness 管理のモデルプロバイダを pi に登録する。
 * 定義の SSOT は model-providers.json（配布コピーを実行時に読む）。
 * key はコピーせず、opencode auth.json への !command 参照 / env 参照に変換する。
 *
 * モデル一覧は静的に書き写さない。`modelsFrom.opencodeCache` を持つプロバイダは、
 * opencode 自身が models.dev から落として更新し続けるローカルキャッシュ
 * （~/.cache/opencode/models.json）を起動時に読み、cost 0 かつ非 deprecated の
 * モデルだけを登録する。`opencode models` が表示する一覧と同じ判定基準なので、
 * 人手で「あれが無い / これが消えた」を追う必要が無い。ネットワークは使わない。
 * SSOT: harunon-harness packages/core/{model-providers.json,pi-extensions/}
 */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const OPENCODE_AUTH = "~/.local/share/opencode/auth.json";
const OPENCODE_MODELS_CACHE = join(homedir(), ".cache", "opencode", "models.json");

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

export interface ModelsFrom {
	/** models.dev cache 内の provider id（例: "opencode"） */
	opencodeCache: string;
	/** true なら cost.input / cost.output が共に 0 のモデルだけ採用する */
	freeOnly?: boolean;
}

export interface CustomProviderDef {
	displayName: string;
	baseUrl: string;
	piApi: string;
	keyRef: KeyRef;
	/** 静的一覧。modelsFrom が解決できた場合はそちらを優先する */
	models?: CatalogModel[];
	modelsFrom?: ModelsFrom;
}

export interface ProviderCatalog {
	customProviders?: Record<string, CustomProviderDef>;
	builtinKeyRefs?: Record<string, KeyRef>;
}

/** models.dev（opencode cache）の 1 モデル分。必要なフィールドだけ型にする */
export interface ModelsDevModel {
	id: string;
	name?: string;
	status?: string | null;
	reasoning?: boolean;
	limit?: { context?: number; output?: number };
	cost?: { input?: number; output?: number };
}

export type ModelsDevCache = Record<string, { models?: Record<string, ModelsDevModel> }>;

export function apiKeyFrom(keyRef: KeyRef): string {
	if (keyRef.opencodeAuth) {
		return `!jq -r ".${keyRef.opencodeAuth}.key" ${OPENCODE_AUTH}`;
	}
	if (keyRef.env) {
		return `$${keyRef.env}`;
	}
	throw new Error("keyRef must specify opencodeAuth or env");
}

/**
 * opencode cache から採用モデルを導出する。`opencode models` と同じく deprecated を除外し、
 * freeOnly なら cost 0 のものに絞る。provider が cache に無ければ null（呼び出し側で fallback）。
 */
export function modelsFromOpencodeCache(
	cache: ModelsDevCache,
	from: ModelsFrom,
	suffix = "",
): CatalogModel[] | null {
	const provider = cache[from.opencodeCache];
	if (!provider?.models) {
		return null;
	}
	const picked: CatalogModel[] = [];
	for (const [id, model] of Object.entries(provider.models)) {
		if (model.status === "deprecated") continue;
		const cost = model.cost ?? {};
		const isFree = (cost.input ?? 0) === 0 && (cost.output ?? 0) === 0;
		if (from.freeOnly && !isFree) continue;
		picked.push({
			id,
			name: `${model.name ?? id}${suffix}`,
			reasoning: model.reasoning === true,
			contextWindow: model.limit?.context ?? 0,
			maxTokens: model.limit?.output ?? 0,
		});
	}
	picked.sort((a, b) => a.id.localeCompare(b.id));
	return picked;
}

export function readOpencodeCache(path = OPENCODE_MODELS_CACHE): ModelsDevCache | null {
	if (!existsSync(path)) {
		return null;
	}
	try {
		return JSON.parse(readFileSync(path, "utf8")) as ModelsDevCache;
	} catch {
		return null;
	}
}

export interface RegisterCall {
	name: string;
	config: Record<string, unknown>;
}

export function resolveModels(def: CustomProviderDef, cache: ModelsDevCache | null): CatalogModel[] {
	if (def.modelsFrom && cache) {
		const derived = modelsFromOpencodeCache(cache, def.modelsFrom, ` (${def.displayName})`);
		if (derived && derived.length > 0) {
			return derived;
		}
	}
	return def.models ?? [];
}

export function buildRegisterCalls(
	catalog: ProviderCatalog,
	cache: ModelsDevCache | null = null,
): RegisterCall[] {
	const calls: RegisterCall[] = [];
	for (const [name, def] of Object.entries(catalog.customProviders ?? {})) {
		calls.push({
			name,
			config: {
				name: def.displayName,
				api: def.piApi,
				baseUrl: def.baseUrl,
				apiKey: apiKeyFrom(def.keyRef),
				models: resolveModels(def, cache).map((model) => ({
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
	const cache = readOpencodeCache();
	for (const call of buildRegisterCalls(catalog, cache)) {
		pi.registerProvider(call.name, call.config as Parameters<ExtensionAPI["registerProvider"]>[1]);
	}
}

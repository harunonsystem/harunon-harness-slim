// model-providers
//
// harness の model-providers.json（LLM プロバイダ定義の SSOT、配布コピー）を読み、
// OpenCode ネイティブ対応でないカスタムプロバイダを config hook で注入する。
// pi 側の等価物は pi-extensions/harness-providers.ts。
//
// 設計原則:
//   - opencodeNative: true のプロバイダは注入しない（models.dev + auth.json に任せる）
//   - opencode.json に同名プロバイダが手書きされていたらそちらを優先（上書きしない）
//   - key の値は持たない。keyRef.env → "{env:NAME}"、keyRef.opencodeAuth → 省略
//     （OpenCode が auth.json のプロバイダ名エントリで解決する）

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 配布レイアウト: runtime/harunon-opencode/model-providers.js（自ファイル）の親に
// runtime/model-providers.json が配布される。configDir 直下の二重配布は廃止済み
const CATALOG_PATH = fileURLToPath(new URL("../model-providers.json", import.meta.url));

export function buildProviderEntries(catalog) {
  const entries = {};
  for (const [name, def] of Object.entries(catalog.customProviders ?? {})) {
    if (def.opencodeNative) continue;
    const models = {};
    for (const model of def.models ?? []) {
      models[model.id] = { name: model.name };
    }
    const options = { baseURL: def.baseUrl };
    if (def.keyRef?.env) {
      options.apiKey = `{env:${def.keyRef.env}}`;
    }
    entries[name] = {
      npm: def.opencodeNpm,
      name: def.displayName,
      options,
      models,
    };
  }
  return entries;
}

export const ModelProviders = async () => {
  return {
    config: async (config) => {
      if (!existsSync(CATALOG_PATH)) return;
      const catalog = JSON.parse(readFileSync(CATALOG_PATH, "utf8"));
      const entries = buildProviderEntries(catalog);
      config.provider = { ...entries, ...(config.provider ?? {}) };
    },
  };
};

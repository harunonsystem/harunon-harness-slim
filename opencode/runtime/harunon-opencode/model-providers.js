// model-providers
//
// harness の model-providers.json（LLM プロバイダ定義の SSOT）を OpenCode の provider
// エントリに射影する関数だけを置く。harunon-v2.js は射影結果が空でなければ（非ネイティブの
// provider があれば）起動を拒否する。
// pi 側の等価物は pi-extensions/harness-providers.ts。
//
// 設計原則:
//   - opencodeNative: true のプロバイダは射影しない（models.dev + auth.json に任せる）
//   - key の値は持たない。keyRef.env → "{env:NAME}"、keyRef.opencodeAuth → 省略
//     （OpenCode が auth.json のプロバイダ名エントリで解決する）

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

# rulesync ソース置き場

外部 skill / rule を `rulesync add owner/repo --skills <name>` で追加すると
`.rulesync/skills/.curated/` 等に展開され、`rulesync.lock` に commit SHA が記録される。

- curated 実体（`.curated/`）は .gitignore 対象。lockfile から再現できるため commit しない
- 更新は週次 workflow（.github/workflows/rulesync-update.yml）が PR を切る
- rulesync 本体は mise.toml の `[tools] "npm:rulesync"` でバージョン固定。ローカルは `mise exec -- rulesync ...`
- ローカル検証: `mise exec -- rulesync doctor --strict && mise exec -- rulesync install --frozen`
- `install --frozen` の drift 保護は初回ソース登録（`rulesync add ...`）後に実効化する。ソース未登録の間は no-op
- 生成物（AGENTS.md 等の再生成）は使わない方針のため `generate` はどこでも実行しない。rulesync.jsonc の features は skills のみ明示済み

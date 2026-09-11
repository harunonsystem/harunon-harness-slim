# ADR-005: /copy-skills-to-codex を廃止し /sync-settings に統合

## Status: Accepted

## Context

`/copy-skills-to-codex` は Codex 向けに skills をコピー + frontmatter 変換 + 孤児検出する専用スキルだった。harness の `/sync-settings` が全ターゲットへの配布を一元管理する設計になり、機能が重複。

## Decision

`/copy-skills-to-codex` を廃止。機能は `/sync-settings --push codex` に統合:

- skills コピー + frontmatter 変換: `distribute` の `transform` + `skillsTransform`
- 孤児検出 + 削除: `--push` 実行時の孤児検出フロー
- AGENTS.md 生成: `distribute` の `applyPatches`（2026-07 追記: その後 `expandIncludes` によるfragment 展開へ移行。applyPatches は 2026-07-26 に機構ごと削除 — ADR-003 追記参照）
- rules コピー: `distribute` の通常コピー

## Consequences

- `/copy-skills-to-codex` は core/skills/ から削除済み
- 既存の `~/.codex/skills/copy-skills-to-codex/` も削除済み
- Codex の設定同期は `/sync-settings --push codex` に一本化

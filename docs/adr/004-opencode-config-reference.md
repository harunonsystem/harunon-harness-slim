# ADR-004: OpenCode は config 参照方式で rules/skills を共有

## Status: Superseded（2026-07-26 — bridge self-contained 2026-07-27）

本 ADR の決定は現行実装で置き換えられている:

- rules は `~/.claude/` 参照ではなく**コピー配布**（`packages/targets/opencode/config.json` の `rules/` エントリ）。常駐は AGENTS.md のみで、rules/*.md は on-demand で読む運用
- skills は `~/.claude/skills/` 参照ではなく **portable target（`~/.agents/skills`）の直読**。OpenCode がネイティブに `~/.agents/skills` をロードパスに含めるため変換・参照設定とも不要になった
- `claude-hooks-bridge` は `runtime/claude-hooks/` を import 相対で実行する自己完結構成へ移行済み（2026-07-27）。`~/.claude/hooks` への実行時依存はない

経緯の記録として原文を以下に残す。

## Context

OpenCode は `opencode.json` に `instructions`（glob パターンで md ファイルを読み込み）と `skills.paths`（外部ディレクトリからスキルを読み込み）の仕組みがある。Codex Desktop にはこの仕組みがない。

## Decision

- **OpenCode**: ファイルコピーではなく `opencode.json` の設定で `~/.claude/rules/*.md` と `~/.claude/skills/` を参照する。`--push opencode` は AGENTS.md のみ配布し、rules/skills は参照先の整合性チェックのみ行う
- **Codex**: config に外部参照の仕組みがないため、rules と skills はファイルコピーで配布する

## Consequences

- OpenCode は Claude Code の `~/.claude/` が最新であれば自動的に最新の rules/skills を参照する
- Codex は `--push codex` を明示的に実行しないと古いままになる
- OpenCode の `opencode.json` 自体の同期は対象外（MCP・permissions 等はツール固有設定が多い）

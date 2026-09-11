---
name: add-skill-to-repo
description: harunon-harness に新規 skill を追加する。「skill追加」「skills repoに追加」で起動。
argument-hint: "<skill-name> [purpose]"
user-invocable: true
references:
  - ../../../scripts/validate-harness.py
  - ../../../packages/core/commands.md
  - ../../../packages/core/disabled-skills.json
  - ../../../docs/adr/002-core-extras-separation.md
  - ../../../docs/adr/011-external-skills-upstream-as-source.md
---

# add-skill-to-repo

harunon-harness に新規スキルを追加する。

## 定数

- **harness root**: `git rev-parse --show-toplevel` で動的に解決
- **core skills**: `<harness-root>/packages/core/skills/`
- **extras skills**: `<harness-root>/packages/extras/_active/skills/`

## Phase 0: そもそも harness に入れるものか

| 対象 | 置き場所 |
| --- | --- |
| 外部 upstream が正本の skill（`npx skills add` で拾ったもの等） | `rulesync.jsonc` に source を追記して `mise exec -- rulesync install`。**vendoring しない**（ADR-011） |
| harness repo が cwd である前提の運用 skill | repo 直下 `.claude/skills/`（project-local。グローバル配布しない） |
| installer が scripts/ ごと入れるアプリ形式 | `packages/core/unmanaged-skills-allowlist.json` に理由付きで宣言 |
| 上記以外の自作 skill | 下の Phase 1 へ |

外部 skill を `packages/core/skills/` にコピーすると、upstream 更新のたびに二重管理になる。

## Phase 1: 配置先の判定

以下のいずれかに該当するなら **extras**、それ以外は **core**（ADR-002）:

| 判定基準 | 例 |
| --- | --- |
| 会社名・org 名・社内サービス名が出てくる | 社内プロダクト名、org slug |
| 特定プロジェクトのパス構造に依存する | プロジェクト固有のディレクトリ構造 |
| 特定フレームワークの固有規約に依存する | 特定 FW の multi-tenant 規約等 |

迷ったらユーザーに確認。デフォルトは extras（core 汚染を防ぐ）。`.env` の `BLOCKED_TERMS` に載る語が core の本文・`paths:` に混ざると、pre-commit と validator の core-purity チェックが error で落ちる。

## Phase 2: スキル作成

1. 対象ディレクトリに `<skill-name>/SKILL.md` を作成（**ファイル名は大文字 `SKILL.md`**。case-insensitive な macOS では気づけず、validator が検出する）
2. frontmatter の `name` は**ディレクトリ名と一致**させる。`description` に「いつ起動するか」を front-load する
3. `references:` を frontmatter に書く場合、パスは SKILL.md からの相対で解決される。実在しないと error
4. 既存 skill と同じトリガー語圏になるなら、description で棲み分けを明示する

## Phase 3: 配布経路への登録

作っただけでは配布契約に載らない。**core に置いた場合は必須**:

| 登録先 | 内容 | 検証 |
| --- | --- | --- |
| `packages/core/commands.md` | slash command として 1 行追加 | validator が commands.md ↔ skills/ の双方向対応を error 判定 |
| `CONTEXT.md` の管理規模テーブル | skills の件数を +1 | validator が実体と突き合わせ |
| `packages/core/disabled-skills.json` | 特定ランタイムで動かない場合のみ除外を宣言（Claude 専用・MCP 依存など互換性理由に限る） | — |

extras-only の skill は `commands.md` に載せない（validator も除外している）。

skill pack によるキュレーションは 2026-08-19 に廃止済み。core / extras に置いた skill は shared-agents（`~/.agents/skills`）経由で codex / opencode / pi / omp に**全件配られる**。除外機構は `disabled-skills.json` だけ。

## Phase 4: 検証と配布

```bash
"$(mise which python3)" scripts/validate-harness.py                  # メタ整合（登録漏れはここで落ちる）
"$(mise which python3)" scripts/run-tests.py                          # 全テスト（クラス単位並列）
./scripts/bootstrap.sh                                               # 全ターゲットへ配布
```

配布結果は `added` に新 skill の SKILL.md が出ていることで確認する。

commit / push はユーザー確認の上で手動で行う（`/sync-settings` の「commit / push は行わない」節と同じ手順）。新規 worktree は `EnterWorktree(name: <branch>)`、stage は `git add <path>` でファイルを指定し、commit は他コマンドと連結せず単独で実行する。

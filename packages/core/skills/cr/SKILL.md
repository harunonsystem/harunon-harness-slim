---
name: cr
description: コードレビューを実行し、改善提案を提供する。reviewer / architecture-reviewer / security-reviewer の3エージェントを並列fan-outしてPRまたはローカル変更をレビュー。「レビューして」「コードレビュー」「CR」で起動。組み込みの /review とは別物。
argument-hint: "[PR番号 | staged | commit-hash | branch | branch-name]"
---

# /cr - コードレビューコマンド

`reviewer` / `architecture-reviewer` / `security-reviewer` の3エージェントを**1メッセージで並列 spawn**し、PRまたはローカル変更のコードレビューを実行します。各エージェントの担当観点は Step 2 参照。メインセッション（orchestrator）が3者の finding を統合し、建設的な改善提案として提供します。

**PR コメント投稿禁止**: このスキルはレポートを会話内に出力するのみ。`gh api` 等で PR にコメントを投稿しない。PR コメントが必要な場合は投稿前に個別にユーザー確認を取る。

## 使用方法

```
/cr [対象]
```

### 対象の指定
- 引数なし: 現在のローカル変更（staged + unstaged）をレビュー
- `<pr-number>`: 指定したPR番号をレビュー
- `staged`: ステージング済みの変更のみをレビュー
- `<commit-hash>`: 特定のコミットをレビュー
- `branch`: 現在のブランチとベースブランチの差分をレビュー
- `<branch-name>`: 指定ブランチとベースブランチの差分をレビュー

## レビュー手順

### Step 0: プロジェクト判定

プロジェクトルートに `Gemfile` と `app/controllers/` が存在する場合は **Rails プロジェクト**と判定し、`/self-review` に委譲する。以降の Step は実行しない。

委譲の手順: Rails と判定した旨を 1 行ユーザーに伝えたうえで、Skill tool で `self-review` を起動する（`/cr` に渡された引数はそのまま引き継ぐ）。Skill tool が使えない環境では `/self-review` の実行をユーザーに案内して終了する。委譲時は本スキルの Output Contract を生成しない。

### Step 1: 変更差分の取得

baseline を確定してから差分を取る（`rules/review-policy.md`「diff baseline の導出」節）。branch / PR 対象では:

1. `git fetch origin <base>` で base を更新する
2. `BASE=$(git merge-base origin/<base> HEAD)` を求める
3. `git diff --name-only "$BASE"..HEAD` を「変更ファイル」の集合として確定し、`git diff "$BASE"..HEAD` を各 subagent に渡す

引数なし（ローカル変更）/ `staged` / `<commit-hash>` は baseline が自明なので、それぞれ working tree・index・当該 commit の差分をそのまま使う。

変更ファイル集合は各 subagent にも渡し、Step 3 の統合と Step 4 の判定で使う。集合外のファイルの指摘は blocking にできず Out of scope に落とす。

### Step 2: 3エージェント並列レビュー（fan-out）
以下の3 subagent を **1メッセージで同時に spawn** し、Step 1 の差分をそれぞれに渡す:
- `reviewer` — 品質・セキュリティ・パフォーマンス全般 + AI生成コード検証（`rules/core-standards.md`「AI 生成コード検証」節: 存在しないAPI/メソッド、クロスファイル配線漏れ、スコープクリープ、デッドコード、フォールバック/デフォルト値の濫用、冗長な条件分岐、Stateful Regex、不要な後方互換コード）
- `architecture-reviewer` — 構造的基準（Phase Separation, Resolution Responsibility, 抽象化レベル一貫性, インターフェース設計）
- `security-reviewer` — セキュリティ REJECT 基準（注入・XSS・デシリアライズ・暗号・IDOR・SSRF・機密流出）

各 subagent は独立して fact-checking ベースでレビューする（`rules/review-policy.md`「事実確認」節）。3者は互いの finding を見ない。

### Step 3: Finding 統合
**メインセッション（orchestrator）が** 3者の finding を統合する:
1. 各 finding の `finding_id` を維持する（prefix は reviewer=`RVW-`, architecture-reviewer=`ARCH-`, security-reviewer=`SEC-`。付与・再利用ルールは `rules/review-policy.md`「Finding ID 追跡」節に従う）
2. file:line + issue の内容が実質同一な finding は重複除去し、根拠が強い方の記述に一本化する
3. severity 順（critical → major → minor → info）でソートして提示する

### Step 4: 判定
判定はメインセッション（orchestrator）が行う。`rules/review-policy.md` に従い APPROVE / REJECT を判定する。
1件でも REJECT 基準に該当すれば REJECT。条件付き APPROVE は禁止。

## Output Contract

レビュー結果は以下の形式で出力すること:

```markdown
# Code Review Report

## Result: APPROVE / REJECT

## Findings

### Blocking (REJECT grounds)

| finding_id | Status | Severity | File:Line | Issue | Proposed Fix |
| --- | --- | --- | --- | --- | --- |
| RVW-001 | new | critical | `src/foo.ts:42` | 問題の説明 | 修正案 |
| ARCH-001 | new | major | `src/bar.ts:15` | 問題の説明 | 修正案 |

### Non-blocking (Warnings)

| finding_id | Severity | File:Line | Issue | Suggestion |
| --- | --- | --- | --- | --- |
| W-001 | minor | `src/baz.ts:88` | 問題の説明 | 改善案 |

### Out of scope (Information only)

| File:Line | Issue | Note |
| --- | --- | --- |
| `src/other.ts:10` | 問題の説明 | 未変更ファイルのため記録のみ |

## AI Antipattern Check

| Check | Result | Evidence |
| --- | --- | --- |
| 存在しないAPI | PASS/FAIL | エビデンス |
| クロスファイル配線 | PASS/FAIL | エビデンス |
| スコープクリープ | PASS/FAIL | エビデンス |
| デッドコード | PASS/FAIL | エビデンス |
| フォールバック濫用 | PASS/FAIL | エビデンス |
| 冗長条件分岐 | PASS/FAIL | エビデンス |
| Stateful Regex | PASS/FAIL | エビデンス |
| 不要後方互換 | PASS/FAIL | エビデンス |

## Summary

- Blocking: N件
- Non-blocking: N件
- Out of scope: N件
```

### Finding ID のルール

- 全 blocking 指摘に `finding_id` を付与。ID は担当 subagent の prefix 付き（`RVW-001`, `ARCH-001`, `SEC-001`）を統合後も維持する。複数観点の同一指摘を統合した場合は根拠が強い方の ID を残し、統合元 ID を Issue 欄に併記する
- 再レビュー時は前回の finding_id を引き継ぎ、ステータスを更新:
  - `new`: 今回新規検出
  - `persists`: 前回指摘から未修正（エビデンス必須）
  - `resolved`: 前回指摘が修正済み
  - `false_positive`: 再検証で問題なしと判明
  - `overreach`: 技術的には正しいがタスクスコープを超過
- それ以外の運用ルール（finding_id なし指摘の扱い、ID の意味不変性等）は `rules/review-policy.md`「Finding ID 追跡」節に従う

### Severity レベル

| Severity | 定義 |
| --- | --- |
| critical | セキュリティ問題、データ不整合、本番障害リスク |
| major | バグ、REJECT基準（review-policy.md）への違反 |
| minor | 改善推奨だがブロッキングではない |
| info | 情報提供のみ |

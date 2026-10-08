---
name: cr
description: PR・commit・branch・ローカル差分のコードレビュー。「レビューして」「コードレビュー」「CR」で使用。差分とリスクに応じて専門レビューを追加し、根拠のある指摘を会話内に返す。
---

# /cr - コードレビューコマンド

PRまたはローカル変更を読み取りでレビューする。まず対象を確定し、Step 2で必要な観点と担当を選ぶ。

**PR コメント投稿禁止**: このスキルはレポートを会話内に出力するのみ。`gh api` 等で PR にコメントを投稿しない。PR コメントが必要な場合は投稿前に個別にユーザー確認を取る。

## 使用方法

```
/cr [対象]
```

### 対象の指定
- 引数なし: 現在のローカル変更（staged + unstaged + 今回のuntracked）をレビュー
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

`rules/review-policy.md`「diff baseline の導出」に従い、対象の差分と変更ファイル集合を一度取得する。
PR番号指定時はそのPRのmetadataからbase/headを確定し、PRの差分を取得する。
名前付きbranchは指定refを使う。現在のcheckoutのHEADで代用しない。baseが確定できない場合は先に解消する。
fetchや差分取得に失敗したら未確認の範囲を示す。部分レビューはできるが、対象を確認できないままAPPROVEとは報告しない。

担当を分ける場合は対象のref/SHA・変更ファイル集合・差分・適用規約を渡し、同じ差分を再取得させない。
未変更の呼び出し元は検証根拠として読めるが、集合外の指摘はOut of scopeにする。

### Step 2: 観点と担当を選ぶ

小さな差分・単一モジュールはメインが品質・回帰・セキュリティを確認する。
広い独立調査は次の担当へ分け、同じ範囲・観点を重複して委譲しない。

- `reviewer`: 一般品質、配線・回帰、AI生成コード検証。基準は `rules/core-standards.md` の該当節。
- `architecture-reviewer`: 複数モジュールの責務・依存方向・公開契約が変わる場合。
- `security-reviewer`: 外部入力、認証認可、機密、危険なsink、CI/CDの信頼境界が変わる場合。詳細は [security-sinks](references/security-sinks.md) の該当言語。

役割名は利用可能なagent定義へ対応させる。専門agentがなければメインで同じ観点を確認する。
独立した担当は並列に実行し、互いのfindingを渡さない。各担当は実ファイルで事実確認する。

### Step 3: Finding 統合
メインが担当者のfindingを統合する。直接レビュー時も同じ基準を使う:
1. 各 finding の `finding_id` を維持する（prefix は reviewer=`RVW-`, architecture-reviewer=`ARCH-`, security-reviewer=`SEC-`。付与・再利用ルールは `rules/review-policy.md`「Finding ID 追跡」節に従う）
2. file:line + issue の内容が実質同一な finding は重複除去し、根拠が強い方の記述に一本化する
3. severity 順（critical → major → minor → info）でソートして提示する

### Step 4: 判定
判定はメインセッション（orchestrator）が行う。`rules/review-policy.md` に従い、確認済みの結果は APPROVE / REJECT、必要な確認が未完了なら INCOMPLETE を使う。
1件でも REJECT 基準に該当すれば REJECT。条件付き APPROVE は禁止。

## Output Contract

対象・判定・必要な根拠を短く出す。正常項目の表や空の Finding 表は作らない。

```text
Code review: APPROVE | REJECT | INCOMPLETE
対象: local / staged / commit / branch / PR、比較ref/SHA、変更ファイル数
Findings: ID [status] [severity] file:line — 影響・根拠・修正案（なければ「なし」）
検証: 実行した検査と結果。AI生成コードの観点は対象に応じて確認し、異常だけ詳述
未確認: 不足資料・未実行の必要な検証と理由（なければ省略）
次: 必要な修正・確認、またはレビュー完了
```

blocking / warning / out-of-scope を混同せず、指摘がある区分だけ示す。
対象外の変更はレビュー範囲の説明にまとめ、問題を確認していなければfinding件数に数えない。
必要な差分・根拠を確認できず、確定したブロッキング問題もない場合は `INCOMPLETE`。
既知の問題があれば `REJECT` とし未確認も併記する。検査を実行していなければ成功と書かない。

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

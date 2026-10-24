---
name: cr
description: PR・commit・branch・ローカル差分のコードレビュー。「レビューして」「コードレビュー」「CR」で使用。差分とリスクに応じて専門レビューを追加し、根拠のある指摘を会話内に返す。
---

# /cr - コードレビューコマンド

PRまたはローカル変更を読み取りでレビューする。まず対象を確定し、必要な観点と担当を選び、blocking candidate は独立に再検証してから判定する。

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

### Step 1: 変更差分と review contract を取得する

`rules/review-policy.md`「diff baseline の導出」に従い、対象の差分と変更ファイル集合を一度取得する。
PR番号指定時はそのPRのmetadataからbase/headを確定し、PRの差分を取得する。
名前付きbranchは指定refを使う。現在のcheckoutのHEADで代用しない。baseが確定できない場合は先に解消する。
fetchや差分取得に失敗したら未確認の範囲を示す。部分レビューはできるが、対象を確認できないままAPPROVEとは報告しない。

repo root に `REVIEW.md` があれば必ず読む。そこにある repo 固有の重点観点、既知ノイズ、risk hint を適用し、全 project 共通ルールへ一般化しない。存在しない場合は `rules/review-policy.md` と対象 repo の AGENTS.md / CLAUDE.md / rules / 近い既存実装を使う。

担当を分ける場合は対象のref/SHA・変更ファイル集合・差分・適用規約を渡し、同じ差分を再取得させない。
未変更の呼び出し元は検証根拠として読めるが、集合外の指摘はOut of scopeにする。
定数・一覧・レスポンス形を変えた差分は、集合外のテストが旧値を期待していないかを検索する。更新漏れは差分起因の回帰として扱う。
生成物（別repo・generatorの出力）の差分は、直接編集と断定する前に生成元の変更（対応PR等）を確認する。生成元が示されていなければ記載を求める。

### Step 2: 観点と担当を選ぶ

小さな差分・単一モジュールはメインが品質・回帰・セキュリティを確認する。
非自明な差分では、少なくとも1つの fresh context の独立 reviewer を使えるなら使う。広い独立調査は次の担当へ分け、同じ範囲・観点を重複して委譲しない。

- `reviewer`: 一般品質、配線・回帰、AI生成コード検証。基準は `rules/core-standards.md` の該当節。
- `architecture-reviewer`: 複数モジュールの責務・依存方向・公開契約が変わる場合。
- `security-reviewer`: 外部入力、認証認可、機密、危険なsink、CI/CDの信頼境界が変わる場合。詳細は [security-sinks](references/security-sinks.md) の該当言語。

役割名は利用可能なagent定義へ対応させる。専門agentがなければメインで同じ観点を確認する。
独立した担当は並列に実行し、互いのfindingを渡さない。各担当は実ファイルで事実確認する。
security-sensitive な差分では security review を一般品質 review と別 lane にする。一般 reviewer の「問題なし」で security lane を省略しない。

### Step 3: candidate finding を統合する

メインが担当者のcandidate findingを統合する。直接レビュー時も同じ基準を使う:
1. 各 finding の `finding_id` を維持する（prefix は reviewer=`RVW-`, architecture-reviewer=`ARCH-`, security-reviewer=`SEC-`。付与・再利用ルールは `rules/review-policy.md`「Finding ID 追跡」節に従う）
2. file:line + issue の内容が実質同一な finding は重複除去し、根拠が強い方の記述に一本化する
3. pre-existing issue、linter が機械的に捕まえるだけの指摘、一般論、再現条件のない pedantic nit は blocking candidate から落とす
4. severity 順（critical → major → minor → info）で並べる

この時点の `critical` / `major` はまだ REJECT 根拠ではない。Step 4 の検証を通して確定する。

### Step 4: blocking candidate を独立に再検証する

各 `critical` / `major` candidate を1件ずつ再検証する。

- fresh context の verifier / reviewer subagent が使える場合、**candidate finding、対象ref/SHA、必要最小限の関連ファイル・契約だけ**を渡す。他の finding、元 reviewer の結論、全体判定は渡さない。
- 独立 agent が使えない場合、メインが実ファイル、呼び出し元、型・schema、既存テスト、必要なら再現コマンドを直接確認する。
- verifier は「もっともらしいか」ではなく、実際に failure が起きるか、または明示契約へ違反するかを確認する。

結果:

- `confirmed`: blocking finding として残す。file:line、影響、再現または契約根拠を付ける。
- `false_positive`: blocking から落とし、必要なら Finding ID の履歴だけ維持する。
- `overreach`: 技術的提案としては妥当でもタスク外なら非ブロッキングへ移す。
- `unverified`: 必要な資料・環境へアクセスできず確認できない。問題を事実として断定せず「未確認」に移す。material risk を否定できない場合だけ全体を `INCOMPLETE` にする。

`minor` / `info` は原則この二段階検証を要求しない。ただし根拠が曖昧なら報告しない。

### Step 5: change risk と判定を出す

まず change risk を `low` / `medium` / `high` に分類する。author やモデル名ではなく、差分の blast radius と rollback 難度で決める。

`REVIEW.md` に risk hint があればそれを優先する。なければ fallback は次:

- `low`: docs / copy / comments / test-only、runtime behavior に到達しない変更、無効な feature flag の後ろに閉じた additive change
- `high`: auth / authorization / secret / trust boundary、破壊的 data change、CI / release / installer / updater、permission / publication gate、重大な public contract 変更
- `medium`: 上記以外の通常の behavior / config / cross-module change

risk tier は human approval の代替ではない。repo の branch rule / CODEOWNERS / team policy が人間承認を要求する場合、AI review はその slot を満たしたと報告しない。

判定はメインセッション（orchestrator）が行う。`rules/review-policy.md` に従い、確認済みの結果は APPROVE / REJECT、必要な確認が未完了なら INCOMPLETE を使う。
`confirmed` な REJECT 基準が1件でもあれば REJECT。条件付き APPROVE は禁止。

## Output Contract

対象・判定・risk・必要な根拠を短く出力する（正常項目の表や空の Finding 表は作らない）。
出力形式、Finding ID 規則（`RVW-`, `ARCH-`, `SEC-`）、および Severity 定義は [output-contract](references/output-contract.md) を参照。

```text
Code review: APPROVE | REJECT | INCOMPLETE
Risk: low | medium | high — 分類根拠
対象: local / staged / commit / branch / PR、比較ref/SHA、変更ファイル数
Findings: ID [status] [severity] file:line — 影響・根拠・再現/契約・修正案（なければ「なし」）
検証: blocking candidate の再検証と、実行した検査の結果
未確認: 不足資料・未実行の必要な検証と理由（なければ省略）
Human gate: repo規則で必要な場合だけ記載。AI review を人間承認済みとは書かない
次: 必要な修正・確認、またはレビュー完了
```

## Frequently Used Commands

> **skill は全件配布**（skill pack によるキュレーションは 2026-08-19 に廃止）。これはコマンド総覧です。runtime ごとに利用可能な skill は異なるため、実際に使える skill を選んでください。

> **upstream 由来 skill の読み替え**: `mattpocock/skills` からrulesyncで取得するskill は本文を逐語で保つため、harness に無い名前を指すことがあります。`to-spec` → `/to-prd`、`to-tickets` → `/to-issues`、upstream の code-review skill → Claude では同名の native skill、他runtimeではその環境で利用可能なレビュー機能を選んでください。`/cr` は非Claude向け配布から除外されています。issue tracker の規約は `rules/core-standards.md`「Issue tracker の規約」節。

### Review / Code Quality

| Command | Purpose |
| --- | --- |
| `/cr` | コードレビュー（reviewer エージェント）。組み込みの `/review` とは別物 |
| `/pre-review-check` | /codex:review 前の統合自己チェック（11 カテゴリ検証 → ponytail-review / similarity-check で機械クリーンアップ） |
| `/unslop` | AIらしい定型表現・冗長な構文を削り、意味とトーンを保って自然な文章に整える |
| `/japanese-tech-writing` | 日本語の技術文書・PR本文を具体的で検証可能な文章に整える |
| `/codex:review` | Codex コードレビュー（push 前1回のみ） |
| `/codex:rescue` | Codex に実装・調査を委譲 |
| `/difit` | difit で差分レビュー依頼 / findings コメント付き差分表示 |
| `/ocr-review` | OpenCodeReview CLI を canonical な diff レビュー engine として実行（pi / omp 用） |
| `/similarity-check` | 差分の言語から選ぶ重複コード検出（TS/JS、Python、Rust、CSS、Markdown、Elixir） |

### Plan / Design

| Command | Purpose |
| --- | --- |
| `/derive-optimal-solution` | 問題の再構成・案の比較。実装前の必須工程ではない |
| `/grilling` | インタビューの本体。決定ツリーをラウンド単位で聞き、フロンティアが空になるまで回す（upstream 逐語） |
| `/grill-implementation` | 実装方針の未決事項を対話で解決。明確な依頼・合意済み方針は再確認しない |
| `/grill-me` | upstream の alias。`/grilling` を回すだけで実装着手の契約は持たない（実装方針の未決事項には `/grill-implementation`） |
| `/grill-with-docs` | ADR / glossary を残しながらのインタビュー。記録が目的なので `/grilling` を回す |
| `/domain-modeling` | ドメインモデル構築・CONTEXT.md / ADR 更新（model-invoked） |
| `/codebase-design` | deep module 設計の共通語彙（model-invoked） |
| `/prototype` | 設計検証用プロト（単一 HTML の logic demo / UI variations） |
| `/research` | 一次情報に当たる調査を background agent に投げ、Markdown で回収（`/wayfinder` の research チケットの解決手段） |
| `/improve` | コードベース監査 → 他モデル実行用の自己完結プラン生成（read-only、shadcn/improve） |
| `/source-driven-development` | フレームワーク判断を一次情報で検証する |

### Diagram / Architecture

| Command | Purpose |
| --- | --- |
| `/archify` | リポジトリやシステムの構成・workflow・sequence・dataflow・lifecycleを検証可能なHTML/SVGへ図式化 |
| `/show-me` | コード・処理フロー・UI構造を最小限の図・Mermaid・コード形状で視覚的に説明 |

### Implementation

| Command | Purpose |
| --- | --- |
| `/run-change` | Agentを跨いで lifecycle / policy gate / evidence を共有するCore Workflowを開始・再開する（worker実行はruntime-native orchestration） |
| `/implement-issue` | PRD または GitHub/Linear issue から実装 |
| `/tdd` | Red-Green-Refactor で実装 |
| `/diagnosing-bugs` | バグ・性能回帰の規律ある診断ループ（旧 diagnose） |
| `/improve-codebase-architecture` | アーキ改善・deepening opportunity 発掘（バグ/セキュリティ/テスト/perf の一般監査で実行プランが欲しいときは `/improve`） |
| `/resolving-merge-conflicts` | git merge/rebase conflict の解消 |

### Issue / PRD

| Command | Purpose |
| --- | --- |
| `/to-prd` | 会話文脈を PRD 化して tracker に publish |
| `/to-issues` | PRD/プランを vertical slice issue に分割 |
| `/triage` | 受信 issue / 外部 PR の state-machine トリアージ |
| `/wayfinder` | 1セッションで持ちきれない規模の作業を issue tracker 上のチケット地図として計画し、1枚ずつ解決 |
| `/decompose-issues` | 機能・エピックの Issue 分解 |

### Figma / Design System

| Command | Purpose |
| --- | --- |
| `/figma-implement` | Figma デザインから UI 実装 |
| `/impeccable-preflight` | 実装済み UI を Impeccable の決定論的 detector で事前検査 |
| `/uiux-workflow` | baoyu-design → 実装 → impeccable-preflight → better-interface → frontend-verify のUI/UX workflow |
| `/interface-review` | branch / PR / uncommitted change を UI・typography・layout・color・writing・a11y 横断でレビュー |
| `/explain-interface` | Web上のUI・animation・interactionがどう実装されているかを分解して説明 |
| `/break` | component を全 state / scenario に展開して stress test |
| `/variant` | component の複数 variant を作って比較・反復 |

`jakubkrehel/skills` は rulesync の external source として追跡し、`better-*`、`interface-review`、`explain-interface`、`break`、`variant` を harness の通常の skill 配布経路へ載せる。upstream は `rulesync.lock` の commit SHA で pin し、手動の `npx skills add` は使わない。

Design System監査は常駐coreにvendoringせず、必要なプロジェクトでupstreamのDesign System Opsを外部installする。

UI/UX workflow のうち `baoyu-design` は引き続き必要なプロジェクトだけ導入する。**install 前に取得先の SKILL.md を実際に読み、エージェントへの指示として妥当か確認する。** サードパーティ skill の本文はそのままエージェントの信頼された指示になり、install コマンドは upstream のデフォルトブランチ HEAD を都度取得するため、差し替わったことに気づける手段はこの確認しかない。

```bash
pnpm dlx skills add JimLiu/baoyu-design
```

### Browser / 検証

| Command | Purpose |
| --- | --- |
| `/opencli-usage` | OpenCLI の adapter discovery と使い分け |
| `/opencli-browser` | OpenCLI によるブラウザ自動操作 |
| `/opencli-adapter-author` | OpenCLI の site adapter 作成・検証 |
| `/frontend-verify` | フロントエンド UI のスクリーンショット検証 |

### PR / Issue 補助

| Command | Purpose |
| --- | --- |
| `/sentry-fix` | Sentry issue のスキャン → チケット → 実装 → PR |

### Harness / Settings

| Command | Purpose |
| --- | --- |
| `/ai-usage-report` | AI の利用実態をログから棚卸しし、社内申請・月次報告・契約見直しの根拠を作る |
| `/config-tune` | cclens + Claude ネイティブ insights の実測で設定・skill 導線を改善（harness SSOT or ~/.claude へ routing） |
| `/upgrade` | 開発ツール一括アップグレード（mise / OpenCode / Homebrew） |

### Meta（skill / プロンプト改善）

| Command | Purpose |
| --- | --- |
| `/writing-for-agents` | agent向け文書・skill執筆のベストプラクティス |
| `/agent-cli-design` | エージェントに使わせる CLI の設計基準・readiness test・適合性レビュー |
| `/skill-creator` | skill 作成ガイド（構造・progressive disclosure） |
| `/skill-improvement` | 既存 skill の設計・文書・empirical 評価をオーケストレーション |
| `/empirical-prompt-tuning` | プロンプト/スキルの実証的改善 |
| `/setup-matt-pocock-skills` | Matt Pocock 系 workflow skills のセットアップ |

> プロジェクト固有のスキルはこの総覧には含まれず、利用環境側で個別に有効化される。

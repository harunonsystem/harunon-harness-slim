---
name: decompose-issues
description: 大きな機能・エピックをtracer bullet型の縦slice Issueに分解する。Linear（主軸）または GitHub Issues に作成。PRD・Figma・ドキュメントを入力として、単体で検証可能な依存関係付きIssue群を生成。「Issue分解」「タスク分解」「decompose」「Issue切って」「チケット作って」などで起動。
---

# decompose-issues: Issue分解スキル

大きな機能・エピックを Issue に分解する。

**運用前提**: issue 管理は **Linear が主軸**。`config.yml` の `tracker` で `linear` / `github` を選択。デフォルトは `linear`。

## 設定

**実行前に `config.yml` を Read して定数値を取得すること。**
`config.yml` が存在しない場合は `config.example.yml` を読む。

設定ファイル: `decompose-issues/config.yml`（なければ `config.example.yml`）

config.yml の主要な設定:
- `tracker` — `linear`（デフォルト） or `github`
- `assignee` — 全Issueのアサイン先（Linear のユーザー名 or GitHub のハンドル）
- `linear_team` — Linear の team key/id（`tracker: linear` 時）
- `linear_project` — Linear の project name/id（任意。`tracker: linear` 時）
- `layers` — レイヤー名→リポジトリ/Linear ラベルのマッピング（GitHub なら repo、Linear ならラベルを当てる）
- `sub_issue_title_prefix` — Issueタイトルの接頭辞（既存config互換のためキー名は維持）

## 入力

`$ARGUMENTS` に以下のいずれかが含まれる:
- PRD / 仕様ドキュメントのURL or パス
- Figma URL（デザイン参照用）
- Linear issue URL（親 Issue / Epic、主軸）
- GitHub issue URL（親 Issue / Epic、`tracker: github` 時）
- テキストによる機能説明

## Issue構造の原則

```
Epic / Feature（大きな塊）
├── Issue 0: prefactor / migration / 足場作成（後続sliceを簡単にする場合のみ）
├── Issue A: 狭いが完全な end-to-end slice（schema/API/UI/test を必要に応じて含む）
├── Issue B: 次の end-to-end slice
└── Issue C: 追加の end-to-end slice
```

### 分割ルール

- **Issue**: tracer bullet 型の縦sliceに分割する。各sliceは狭いが、完成すると単体で demoable / verifiable であること
- **禁止**: schema / BE / FE のような水平レイヤーだけのIssueを原則作らない。レイヤー作業は各Issue本文の checklist に含める
- **prefactor**: 後続sliceを明確に簡単にする最小変更だけ、先頭Issueとして切り出してよい
- **依存順序**: blocker になる prefactor / shared schema / shared contract を先に置き、以後はユーザー価値が小さくても完結する順に並べる
- **1 Issue = 1 PR**: 1つのIssueは1つのPRで完了できる粒度にする。複数repoにまたがる場合は、最小限の統合sliceとして扱えるかを確認し、難しければユーザーに分割方針を確認する

### 縦slice判定

各Issue案は作成前に以下を満たすか確認する:

- 完成後にユーザーまたはレビュアーが単体で挙動を確認できる
- 必要な schema / API / UI / MSW / Storybook / test が同じIssueの完了条件に入っている
- 「次のレイヤーが来るまで何も確認できない」状態で終わらない
- Issue本文は layer-by-layer の作業指示ではなく、end-to-end の振る舞いを中心に書く

### Issue作成ルール

- `tracker` に応じたツールを使用（`linear`: Linear MCP の `save_issue` / `github`: `gh issue create --repo`）
- アサインは全て `$assignee`
- ラベルは既存のリポジトリラベルから適切に選択（Linear の場合は既存ラベル/プロジェクトから選択）

## ワークフロー

### Phase 1: 情報収集

入力情報を解析し、以下を把握する:

1. **PRD / ドキュメント**: WebFetch or Read で内容を取得
2. **Figma**: `get_metadata` でページ構造を把握（get_design_contextは使わない。構造把握のみ）
3. **既存Issue**: `tracker` に応じて親Issue/Epicの内容を確認（`linear`: Linear MCP の `get_issue` / `github`: `gh issue view`）
4. **対象リポジトリ**: config.yml の `$layers` マッピングから、各レイヤーに対応するリポジトリを使用

### Phase 1.5: grill-implementation（分解方針の stress-test）

**Phase 2 の多角的分析エージェント並列起動の前に `grill-implementation` スキルを invoke する。** 詳細は `skills/grill-implementation/SKILL.md`。

このフェーズで押さえるべき Issue 分解特有の軸:

- 分割の単位（ページ単位 / 機能単位 / レイヤー単位の優先）
- 各Issueを tracer bullet 型の縦sliceにできるか
- リリース順序・Wave 分割の粒度
- どこまでを最小スコープ（MVP 境界）として切り出すか
- `$layers` マッピングに含まれないリポジトリ / レイヤーの要否
- 各 Issue のサイズ感・並列可能性の事前仮説

終了条件: grill-implementation Phase 5 サマリーでユーザー明示承認。grill-implementation の結論は Phase 2 エージェントへの入力として使う。

### Phase 2: 多角的分析（エージェント並列起動）

3つの観点でエージェントを並列起動し、分解案を作成する:

**エージェント1 - ユーザー/リリース観点**:
- ユーザーストーリー単位の tracer bullet slice 候補
- demoable / verifiable な最小単位の特定
- 機能間の依存関係（どの順でリリースすべきか）

**エージェント2 - 技術/アーキテクチャ観点**:
- schema変更の影響範囲
- 各sliceが通る schema / API / FE / test の境界
- リポジトリ間の依存関係
- 後続sliceを簡単にする prefactor 候補

**エージェント3 - リスク/ボリューム観点**:
- 各sliceの見積もり難易度（S/M/L）
- 技術的リスクが高い部分の特定
- 並列作業可能な部分の特定
- slice が大きすぎる / 水平分割に戻っている箇所の指摘

### Phase 3: 統合 & Issue構造の確定

エージェントの分析結果を統合し、Issue構造を確定する。

出力フォーマット（ユーザーに提示）:

```
## Issue分解案

### Wave 1（先行着手）
- [ ] Issue 0: <prefactor / 足場作成タイトル> [repo: <リポジトリ名>] (Size: S, Blocked by: None)
  - What to build: <後続sliceを簡単にする最小変更>
  - Verification: <単体で確認できること>
- [ ] Issue 1: <縦sliceタイトル> [repo: <リポジトリ名>] (Size: S, Blocked by: #0 or None)
  - User stories covered: <該当する user story>
  - What to build: <end-to-end の振る舞い>
  - Layers touched: schema / API / FE / MSW / Storybook / test（必要なものだけ）

### Wave 2（Wave 1完了後）
- [ ] Issue 2: <縦sliceタイトル> [repo: <リポジトリ名>] (Size: M, Blocked by: #1)
  ...

### 依存関係
- Issue 2 は Issue 1 の公開済み contract に依存
- ...
```

提示時には、各Issueについて以下を明示する:

- **Title**: 短い説明名
- **Blocked by**: 先に完了すべきIssue。なければ `None - can start immediately`
- **User stories covered**: 元資料に user story がある場合の対応
- **What to build**: レイヤー別作業ではなく、完成後に確認できる end-to-end の振る舞い
- **Acceptance criteria**: 3〜5項目
- **Layers touched**: `$layers` のうち、このsliceで触る可能性があるもの

**利用中のエージェントのユーザー確認機能で確認を取る**（必須ゲート）:

作成予定のIssue一覧を提示して承認を得る。

質問の `question` に以下を含める:
- 全Issueのタイトル、リポジトリ、Wave、Size、Blocked by、Layers touched の一覧表
- 依存関係の説明
- 「粒度が粗すぎる / 細かすぎる」「依存関係が違う」「merge / split したいsliceがある」場合は修正する旨
- 「この内容でIssueを作成してよいですか？」

選択肢:
- "このまま作成" — Phase 4に進む
- "修正したい" — ユーザーのフィードバックを受けてPhase 3をやり直す

**ユーザーが「このまま作成」を選択するまでPhase 4に進まない。**

### Phase 4: Issue一括作成

承認後、`tracker` に応じてIssueを作成する。各Issueは縦sliceそのものであり、親Issue・Sub-issueの階層は作らない。依存関係は `Blocked by` で表現する。

#### tracker: linear

Linear MCP の `save_issue` を使う。必須パラメータ: `team`（`linear_team`）、`assignee`（`$assignee`）。`linear_project`（`$linear_project`）が設定されていれば `project` も指定する。

1. 依存順（blocker になる prefactor / shared contract を先、以後は Wave 順）に各sliceのIssueを `save_issue` で作成する。パラメータ: `team`=`$linear_team`, `project`=`$linear_project`（あれば）, `assignee`=`$assignee`, `title`=<縦sliceタイトル>, `description`=概要・背景・What to build・受け入れ条件・Implementation checklist・関連リンク・Blocked by（GitHub版のbody構成に準拠）
2. 依存関係があるIssueは、依存先Issueを先に作成してその id を控えたうえで、依存元Issueの `save_issue` 呼び出しに `blockedBy`=[依存先Issueのid] relation を渡す。description にも "Blocked by <issue識別子>" を併記してよい

#### tracker: github

`gh issue create` を使う。

```bash
gh issue create \
  --repo $default_repo \
  --title "<タイトル>" \
  --assignee $assignee \
  --label "<ラベル>" \
  --body "$(cat <<'EOF'
## 概要
<この縦sliceで作る end-to-end の振る舞い>

## 背景
<PRD/ドキュメントからの背景情報>

## What to build
<レイヤー別作業ではなく、完成後に確認できる挙動を簡潔に書く>

## 受け入れ条件
- [ ] <条件1>
- [ ] <条件2>
- [ ] <必要なら loading / error / empty / normal の状態確認>

## Implementation checklist
- [ ] schema / contract（必要な場合）
- [ ] API / service（必要な場合）
- [ ] UI / page（必要な場合）
- [ ] MSW / Storybook / test（必要な場合）

## 関連
- PRD: <URL>
- Figma: <URL>
- 依存Issue: #<number>

## Blocked by
- #<blocking issue number>（なければ None - can start immediately）
EOF
)"
```

##### 作成順序

1. blocker になる prefactor / shared contract のIssueを先に作成
2. 依存順に縦slice Issueを作成
3. 依存関係があるIssue間はbodyに "Blocked by #xxx" を記載

### Phase 5: 作成結果の報告

作成した全Issueのサマリーを報告する:

```
## 作成完了

| Wave | Issue | Repo | Size | URL |
| --- | --- | --- | --- | --- |
| 1 | prefactor: contract足場 | repo-a | S | #123 |
| 1 | ユーザー一覧を表示できる | repo-a | M | #456 |
| 2 | ユーザー詳細から編集できる | repo-a | M | #789 |
```

## ガードレール

- `tracker` 設定に従う: `linear` の場合は Linear MCP の `save_issue`、`github` の場合は `gh issue create --repo` を使用する。**両方に同じ Issue を二重作成しない**
- Phase 3 でユーザー確認を取らずに Issue 作成しない
- 1 Issue = 1 PR の原則を破らない（PR は GitHub）
- schema / BE / FE だけの水平Issueを作りたい場合は、縦sliceにできない理由を明示してユーザーに確認する
- `$layers` マッピングにないレイヤーが必要な場合はユーザーに確認する

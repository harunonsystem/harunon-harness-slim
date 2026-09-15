---
name: implement-issue
description: PRD または Linear task / GitHub issue の URL から worktree を作成し、実装・レビュー・PR 作成まで一貫して行う。URL を渡すか「issue 実装」「タスク実装」などで起動。
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Agent, AskUserQuestion, Skill
---

# implement-issue: Issue実装スキル

PRD、Linear task、GitHub issue の URL、またはタスク説明を受け取り、worktree 作成 → 実装 → セルフレビュー → PR 作成を一貫して行う。

**運用前提**: issue 管理は **Linear が主軸**。GitHub issue は副次的に使用される場合があり、PR は **GitHub** で作成する。

## 入力

`$ARGUMENTS` に **PRD**、**Linear task URL**（主）、GitHub issue URL、またはタスク説明が含まれる。

## 設定

**実行前に `config.yml` を Read して定数値を取得すること。**
`config.yml` が存在しない場合は `config.example.yml` を読む。

設定ファイル: `implement-issue/config.yml`（なければ `config.example.yml`）

config.yml の設定:
- `main_repo` — メインリポジトリのパス（単一リポジトリ運用）
- `repos` — issue ID の prefix → メインリポジトリのパス のマッピング（複数リポジトリ運用。`main_repo` より優先）
- `worktree_cmd` — worktree 管理コマンド（add / list サブコマンド）
- `pr_template` — PR Template のパス
- `lint_fix_cmd` — lint 修正コマンド

`repos` が定義されている場合、Linear task ID（例: `ABC-123`）の prefix（`ABC`）で `repos` を引き、一致したパスを `main_repo` として使う。一致する prefix がなければユーザーに確認する。GitHub issue や PRD など issue ID が取れない入力の場合は `main_repo` を使う（`repos` のみで `main_repo` が無い場合はユーザーに確認する）。

## ワークフロー

### Phase 1: タスク情報の取得

#### PRD の場合
ユーザーが渡した PRD をタスク定義として使用する。複数 issue に分割済みの場合は、今回の `$ARGUMENTS` に含まれる単一 issue のみをスコープとする。

#### Linear task の場合（主軸）
Linear MCP の `get_issue` または WebFetch で Linear URL からタスク情報を取得する。優先順位: MCP > WebFetch。

#### GitHub issue の場合（副）
```bash
gh issue view <issue-number> --repo <owner/repo>
```
`gh` は GitHub 専用ツール。Linear には使えない。

#### 直接説明の場合
ユーザーの説明をそのままタスク定義として使用する。

タスク情報から以下を把握する：
- タスクの目的・背景
- 実装要件
- 受け入れ条件

### Phase 1.5: grill-implementation（実装方針の stress-test）

**実装に着手する前に必ず `grill-implementation` スキルを invoke する。** 方針が未確定のまま worktree 作成・実装に進まない。

決定軸の優先順位・進め方・スキップ基準は `skills/grill-implementation/SKILL.md`（SSOT）に従う。

終了条件: Phase 5 サマリーをユーザーに提示 → 明示的 OK を得る。

### Phase 2: worktree 作成

1. `repos` が設定されている場合、issue ID の prefix から対象リポジトリを解決し `$main_repo` を確定する（解決ロジックは「設定」節を参照）。

2. メインリポジトリで最新の main を取得し、共有 checkout が clean か確認する：
```bash
git -C $main_repo fetch origin --prune
git -C $main_repo status --short   # 出力があれば他セッションの作業。触らずユーザーに報告する
```

2.5. base を確定して表示する（**コードを書く前の必須出力**）：
   - 通常: `origin/main`
   - 既存 PR の上に積む（stacked PR）: `gh pr view <n> --json headRefName,headRefOid` で head を取り、その branch を base にする。`$worktree_cmd add` は既定で origin/main から切るので base の指定を省略しない
   - どちらの場合も base の branch 名・SHA・`git log --oneline -3 <base>` をユーザーに提示し、「この上に積む」と明示してから次へ進む（origin/main から切って stale diff を出した失敗が複数ある）

3. ブランチ名をタスクから決定する：
   - Linear task: `feature/<task-id>-<要約>` or `fix/<task-id>-<要約>`（例: `feature/eng-123-add-foo`）
   - GitHub issue: `feature/<issue内容の要約>` or `fix/<issue内容の要約>`
   - ブランチ名は kebab-case で簡潔に

4. worktree を作成（base が origin/main か stacked かで経路が違う）：
```bash
# base が origin/main:
#   Claude Code: EnterWorktree ツールに name: <branch-name> を渡す。
#   WorktreeCreate hook が main_repo で gwm add <branch-name> を実行する（origin の default branch 起点）。
#   その他: $worktree_cmd add <branch-name>（main_repo で実行）
# stacked PR（2.5 で選んだ base を実際に渡す。EnterWorktree(name:) 経由では base を指定できない）:
#   (cd $main_repo && $worktree_cmd add --from <base-branch> <branch-name>)   # 出力の worktree パスを控える
```

5. worktree ディレクトリに移動（Bash の `cd` ではセッションの作業ディレクトリが変わらない）：
```bash
# Claude Code:
#   base が origin/main → 4 の EnterWorktree(name: <branch-name>) が作成と移動を兼ねるので追加操作なし
#   stacked PR         → EnterWorktree(path: <4 で控えた worktree パス>)
# その他: $worktree_cmd add の出力パスを runtime の worktree 移動機能へ渡す
```
   移動後に `git log --oneline -1` の SHA が 2.5 で提示した base の SHA と一致することを確認する。一致しなければ base の取り違えなので、実装に入らずやり直す。

6. ユーザーに作成した worktree とこれから実装する内容のサマリーを報告する。

### Phase 3: 実装

実装を開始する前に：
- 既存の類似コンポーネント・パターンを確認する
- デザイントークン・CSS 変数を確認する
- 命名規則を既存ファイルから確認する

タスク要件に基づいて実装を行う。CLAUDE.md およびルールファイルの規約に従うこと。

`/tdd` を pre-agreed seams で使用する。型チェックは定期的に、単体テストファイルも定期的に、フルスイートは最後に 1 回実行する。

#### 実装品質基準
- **既存パターン優先**: 同種の機能が既にあれば、その実装パターンをコピーして改変する（新パターン禁止）
- **変更スコープ最小化**: タスク要件に直接関係しないリファクタリング・改善は含めない
- **型安全性**: any/unknown の使用禁止。型推論に頼らず明示的な型定義を行う
- **テスト同時作成**: TDD 原則に従い、実装と対応するテストを同時に作成する

### Phase 4: セルフレビュー

実装完了後、ローカルの変更内容をレビューする。

1. 変更内容の確認：
```bash
git diff --stat
git diff
```

2. 以下の観点でレビュー：
   - **コード品質**: 既存パターンとの一貫性、命名規則、デザイントークン使用
   - **セキュリティ**: マルチテナントスコープ、SQL インジェクション、XSS
   - **TypeScript/React**: props destructuring 規約、`React.FC` 不使用
   - **CSS**: ハードコードされた px 値がないか、CSS 変数を使っているか
   - **不要な変更**: 依頼範囲外の変更が含まれていないか

3. 問題の重要度判断:
   - **即修正**: セキュリティ問題、データ不整合リスク、テスト未作成
   - **修正推奨**: パフォーマンス問題、規約違反、命名不適切
   - **許容**: スタイル差異（Linter が通れば OK）
   即修正の問題がすべて解消されるまで Phase 4.5 に進まない。

### Phase 4.5: レビュー対象の checkpoint commit

Phase 4 の即修正問題が残っていれば、先にすべて解消する。Codex review の証跡は commit SHA に結びつくため、review より先に候補 commit を作る。

1. 変更をコミット：
`--no-verify` 不使用。
```bash
git add <変更ファイル>
git commit -m "$(cat <<'EOF'
コミットメッセージ
EOF
)"
```

Core Workflowを使用中なら、checkpoint後に`committed`へ遷移する。

### Phase 5: Codex レビューと PR 作成

詳細は `rules/codex-review-policy.md`（SSOT）。

#### レビュー

1. 事前に `/pre-review-check`（コード変更を含むなら必須。Codex に回す前に Claude 側で潰せるものを潰す）
2. checkpoint commit の HEAD に対して、Core Workflowが選択したreview adapterを **1 回だけ**実行（background 起動が既定）
3. 結果をユーザーに提示する（指摘は原文のまま。件数や優先度を要約で変えない）
4. 指摘を修正する。ユーザーの選択は待たない
   - P0 / P1 / P2: 同じブランチで修正する。P0 が直せない場合は push / PR に進まず止まって報告する
   - P3 / scope 外: 直さず PR 本文の「残件」に finding 単位で列挙する
   - 修正はレビュー対象の差分に閉じる（無関係な未 commit 変更を巻き込まない）。commit は通常の Git 規約どおりユーザー確認のうえ、対象ファイルを明示して行う。Core Workflow 使用中は `findings_fixed` で decide → publish に進める（再レビューはしない。PR gate はレビュー済み commit が HEAD の祖先なら通す）
5. reviewer が quota / credit 切れで返らなかった場合は SKIP: `~/.claude/hooks/codex-review-bypass.sh --quota "<エラー要旨>"`（Core Workflow 使用中は kernel にも `review.skip` が記録される）を実行し、PR 本文に「Codex review: SKIP（quota）」と書く。接続・認証・crash など quota 以外の失敗は止まってユーザーに確認する
6. 2 回目の review はユーザーが明示的に許可した場合だけ実行する

#### 公開

1. リモートに push：
```bash
git push -u origin <branch-name>
```

2. PR Template を読み込み、PR description を生成して PR を作成する：
   - まず `cat $pr_template` でテンプレートを読み込む
   - テンプレートのセクションに沿って書く。**埋めるために項目を作らない**（書くことがないセクションは省略可）
   - body 例をハードコードしない。必ず実際のテンプレートの構造・セクション・チェックリストをそのまま使う
   - 出力品質の基準: **ファイルパス・関数名・ライブラリ API 名は書かない**、Summary 1-2 行、Changes 最大 3-5 項目、Test plan は手動検証のみ
```bash
gh pr create --title "<PRタイトル>" --body "$(cat <<'EOF'
<PR Templateの各セクションを埋めた内容>
EOF
)"
```

3. 作成された PR URL をユーザーに報告する。

4. `cr` skill で最終レビューを行う。

## ガードレール

### 実装中の合意事項保持（軌道修正の最大の原因）

- Phase 3 開始時、grill-implementation Phase 5 サマリーを再読してから実装に入る
- Phase 4 開始時、サマリーと diff を照合し、**逸脱があれば実装に戻る前にユーザーに確認**（勝手に「やっぱり X」としない）
- 実装中に判断が分かれる場合は、ユーザー回答を受けるまで該当箇所の実装を保留し、他の領域を進める
- サマリーの「保留事項」が実装に関わったら、停止してユーザーに質問

### スコープと入力の扱い

- 実装中のユーザーメッセージが**状態確認・診断だけを求めている**場合、answer-first モード（CLAUDE.md Response Mode 参照）。その質問を根拠に新しい編集を始めない。判定は句読点ではなく意図で行う（「これ直せる?」は変更依頼、「テスト通った?」は状態確認）
- answer-first で回答した後、**進行中の承認済み実装はそのまま継続する**。止めるのはユーザーが停止・取消・方針変更を指示した時だけ

### Git 操作

- `git commit --no-verify` 禁止。エラーが起きた場合は `$lint_fix_cmd` で解消する
- commit 前に `git rev-parse --show-toplevel` と `git branch --show-current` で意図したブランチ確認
- ブランチ名は既存の worktree と重複しないよう `$worktree_cmd list` で確認する
- base branch への独断マージ禁止（preview push は push 先指定を守る）

## 注意事項

- コミット・push・PR 作成は、**既存の依頼・承認がその操作を明示的に含むか**を操作ごとに判定する。含むなら再質問しない（例: 明示的な PR 作成依頼は PR 作成の承認）。含まれない操作だけ実行前に確認を取る。ある操作の承認を別の操作（PR 作成の依頼 → commit / push / merge）まで広げない。platform 側の権限確認は別途そのまま表示する
- Linear task / GitHub issue がある場合、PR description にリンクを含める（Linear がある場合は Linear を主にリンク）

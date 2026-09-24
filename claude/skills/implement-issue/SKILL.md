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

### Phase 1.5: 未決事項の確認

既存コード・タスク記述・既存の合意から実装範囲を確認する。ユーザー判断が必要な未決事項があるとき、またはインタビューを依頼されたときだけ `grill-implementation` を使う。要件が明確なら Phase 2 へ進む。

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

対象 repo の指示、既存実装、検証コマンドに従い、要件に必要な変更とテストを行う。新しい挙動・不具合修正は失敗を再現する検証から始める。文言や設定だけの変更では、効果を確認できる最小の検証を選ぶ。

### Phase 4: セルフレビュー

実装完了後、ローカルの変更内容をレビューする。

1. 変更内容の確認：
```bash
git diff --stat
git diff
```

2. 受け入れ条件・変更範囲・repo の品質基準と照合し、変更に関係する不具合やセキュリティリスクを確認する。lint / typecheck / test は repo のコマンドを使い、結果を記録する。

3. 未解決の重大な不具合・データ不整合・必要な検証の欠落があれば、checkpoint 前に解消する。不要な新規テストやスタイル変更を増やさない。

### Phase 4.5: レビュー対象の checkpoint commit

Phase 4 の未解決問題が残っていれば、先に解消する。Codex review の証跡は commit SHA に結びつくため、review より先に候補 commit を作る。

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

2. `rules/pr-body.md` を読み、PR Template があれば併せて読み込んで PR description を生成する：
   - まず `cat $pr_template` でテンプレートを読み込む
   - テンプレートのセクションに沿って書く。**埋めるために項目を作らない**（書くことがないセクションは省略可）
   - body 例をハードコードしない。実際のテンプレートの構造・セクション・チェックリストを保ち、その各欄に `rules/pr-body.md` の情報優先度を適用する
   - Evidence には before → after の証拠と、実際に実行した test / lint / typecheck / build の結果を書く。未実行は理由を明記する
```bash
gh pr create --title "<PRタイトル>" --body "$(cat <<'EOF'
<PR Templateの各セクションを埋めた内容>
EOF
)"
```

3. 作成された PR URL をユーザーに報告する。

4. 追加レビューはユーザーの依頼、または未確認の具体的なリスクがある場合だけ行う。既に確認済みの同じ差分を再レビューしない。

## ガードレール

### 実装中の合意事項保持（軌道修正の最大の原因）

- 実装時はタスクの受け入れ条件と既存の合意を参照する。インタビューした場合はそのサマリーも使う
- レビュー時は受け入れ条件と diff を照合する。合意した仕様を変更する必要がある場合だけ、その判断を確認する
- ユーザー固有の判断が残る部分だけ保留し、独立した作業は続ける。既存規約で決まる実装上の細部は自分で解決する
- サマリーの「保留事項」が実装に関わったら、停止してユーザーに質問

### スコープと入力の扱い

- 実装中のユーザーメッセージが**状態確認・診断だけを求めている**場合、まず質問に回答する。その質問を根拠に新しい編集を始めない。判定は句読点ではなく意図で行う（「これ直せる?」は変更依頼、「テスト通った?」は状態確認）
- answer-first で回答した後、**進行中の承認済み実装はそのまま継続する**。止めるのはユーザーが停止・取消・方針変更を指示した時だけ

### Git 操作

- `git commit --no-verify` 禁止。エラーが起きた場合は `$lint_fix_cmd` で解消する
- commit 前に `git rev-parse --show-toplevel` と `git branch --show-current` で意図したブランチ確認
- ブランチ名は既存の worktree と重複しないよう `$worktree_cmd list` で確認する
- base branch への独断マージ禁止（preview push は push 先指定を守る）

## 注意事項

- コミット・push・PR 作成は、**既存の依頼・承認がその操作を明示的に含むか**を操作ごとに判定する。含むなら再質問しない（例: 明示的な PR 作成依頼は PR 作成の承認）。含まれない操作だけ実行前に確認を取る。ある操作の承認を別の操作（PR 作成の依頼 → commit / push / merge）まで広げない。platform 側の権限確認は別途そのまま表示する
- Linear task / GitHub issue がある場合、PR description にリンクを含める（Linear がある場合は Linear を主にリンク）

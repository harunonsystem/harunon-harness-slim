---
name: implement-issue
description: PRD・Linear task・GitHub issue から要件と worktree を解決し、必要に応じて run-change に引き継いで実装・レビュー・PR 作成まで進める。「issue 実装」「タスク実装」で起動。
---

# implement-issue: Issue実装スキル

PRD、Linear task、GitHub issue の URL、またはタスク説明を受け取り、要件と worktree を解決する。コード変更は `run-change` の Core Workflow に引き継いで PR 作成まで進める。

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

既存コード・タスク記述・既存の合意から目的と実装範囲を確認する。手段が未承認の提案か未指定で、既存機構を含む実質的に異なる解法が複数残る場合は `derive-optimal-solution` で比較してから進む。ユーザー固有の判断が残るとき、またはインタビューを依頼されたときだけ `grill-implementation` を使う。方針が決まれば Phase 2 へ進む。

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

### Phase 3: 実装への引き継ぎ

worktree に移動したら `run-change` skill を読み、その worktree を cwd にして status を確認する。同じ task の active state は再開し、別 task の active state を上書きしない。state が無いか inactive の場合、変更対象がすべて Markdown 等で `rules/codex-review-policy.md` の review 免除に該当するなら、Core Workflow を開始せず repo の検証・公開規約に従う。実装中に review 対象のファイルが加わったら、review・公開前に `run-change` を開始する。それ以外は Linear ID、GitHub の `<owner/repo>#<number>`、または PRD・直接説明から決めた branch 名で開始する。Phase 1〜2 で確定した issue 情報や worktree を取り直さない。

次の情報を実行側の context に渡す：目的、受け入れ条件、task URL / ID、対象 repo、base と branch、repo の検証コマンド、既存の公開承認。設定済みなら `pr_template` と `lint_fix_cmd` も使う。Core Workflow を開始した場合は取得・隔離済みの事実を遷移として記録し、以後の lifecycle、policy gate、review evidence、PR 作成は `run-change` の手順と repo の規約に従う。worker の選択や実装は runtime-native の実行面が担う。

**完了条件**: 受け入れ条件に照らした変更と検証結果があり、許可された公開操作を終え、PR を作成した場合は URL を報告している。許可がない操作だけは実行前に確認する。

## 作業中の入力と公開

- 状態確認の質問には実測を先に答え、その質問だけを理由に新しい編集を始めない。回答後は承認済みの実装を継続する。「直せる?」など具体的な変更依頼は句読点でなく意図で判定し、元の依頼から実質的に範囲が広がる場合だけ確認する。
- commit、push、PR 作成、merge は操作ごとに既存の依頼・承認を確認する。明示的な PR 作成依頼について同じ確認を繰り返さず、merge の承認には広げない。platform 側の権限確認はそのまま扱う。

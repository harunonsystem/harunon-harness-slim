---
name: implement-issue
description: PRD・Linear task・GitHub issue から要件と worktree を解決し、実装へ引き継ぐ。spec が足りない task は実装せず、spec を整える入口へ回す。「issue 実装」「タスク実装」で起動。
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Agent, AskUserQuestion, Skill
---

# implement-issue: Issue実装スキル

`yomiyasu` は利用可能な場合だけ使用する。未導入の場合は、各手順の制約を保ち、その場で表現だけを推敲する。

PRD、Linear task、GitHub issue の URL、またはタスク説明を受け取り、要件と worktree を解決したら、常駐指示の Routing に従って実装へ引き継ぐ。この skill は実装手順を持たず、pstack の手順も複製しない。

issue tracker は入力 URL とプロジェクト設定に従う。この skill は Linear / GitHub Issues を扱い、PR は GitHub に作成する。

## 入力

`$ARGUMENTS` に PRD、Linear task URL、GitHub issue URL、またはタスク説明が含まれる。

## 設定

**実行前に `config.yml` を Read して定数値を取得すること。**
`config.yml` が存在しない場合は `config.example.yml` を読む。

設定ファイル: `implement-issue/config.yml`（なければ `config.example.yml`）

config.yml の設定:
- `main_repo` — メインリポジトリのパス（単一リポジトリ運用）
- `repos` — issue ID の prefix → メインリポジトリのパス のマッピング（複数リポジトリ運用。`main_repo` より優先）
- `worktree_cmd` — 任意の worktree 管理コマンド（`add --from <base> <branch>` に対応するもの）。未設定なら runtime 標準機能か Git を使う。global / project 指示に指定があればそちらを優先する
- `pr_template` — PR Template のパス
- `lint_fix_cmd` — lint 修正コマンド

`repos` が定義されている場合、Linear task ID（例: `ABC-123`）の prefix（`ABC`）で `repos` を引き、一致したパスを `main_repo` として使う。一致する prefix がなければユーザーに確認する。GitHub issue や PRD など issue ID が取れない入力の場合は `main_repo` を使う（`repos` のみで `main_repo` が無い場合はユーザーに確認する）。

## Phase 0: 既存 task の再開確認

issue 情報を取得する前に、入力から task ID / 対象 repo を解決し、`git worktree list` と対象 worktree の `run-change` status (`python3 <run-change-skill-dir>/scripts/harness.py --repo <worktree> status`。`<run-change-skill-dir>` は同じ配布 skills ディレクトリ内の `run-change/` を指す) を確認する。GitHub PR に関係する再開では `status --pr <既知の番号またはURL>`、番号がなければ `status --pr` で実状態も照合し、[run-change の再開・handoff](../run-change/SKILL.md#resume-and-handoff) に従う。その照合後、会話内の accepted intake 情報と task ID・repo・worktree が一致する場合は、state の有無にかかわらず既存情報を再利用して Phase 3 へ進み、Phase 1〜2 を繰り返さない。active state がある場合は task ID も一致することを確認する。別 task の state は変更せず、その worktree を今回の task に使わない。task / repo / worktree / intake を確認できない新規依頼だけ Phase 1 以降の未解決手順へ進む。

## ワークフロー

### Phase 1: タスク情報の取得

#### PRD の場合
ユーザーが渡した PRD をタスク定義として使用する。複数 issue に分割済みの場合は、今回の `$ARGUMENTS` に含まれる単一 issue のみをスコープとする。

#### Linear task の場合
Linear MCP の `get_issue` または WebFetch で Linear URL からタスク情報を取得する。優先順位: MCP > WebFetch。

#### GitHub issue の場合
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

### Phase 1.5: 着手判定

この skill は、そのまま実装に入れる task だけを扱う。入力の種類（sub-issue・親 Issue・PRD・直接説明・調査レポート）ではなく、中身で判定する。

- **着手できる**: 目的、受入条件、範囲外が入力・会話・repo から確定でき、Blocked by が全部完了している。技術設計と解法選択は実装側で決めるので、判定に含めない
- **blocker が未完了**: 未完了の Issue を示して止まる
- **spec が足りない**: 受入条件または範囲を確定できない、product の判断が決まっていない、1 本の振る舞いに収まらない。範囲外が明記されていなくても、1 本の振る舞いや修正対象から範囲が決まるなら足りている。worktree を作らず、不足を示して spec を整える入口へ回して止まる。その場で product の判断を聞き始めない
  - 人と詰める: `grill-with-docs` → `to-spec` → `to-tickets`
  - agent が repo・契約に当てて整える: `spec-ready`

判定のためにも、止まるときにも tracker へ書き込まない。tracker の扱いは `rules/issue-tracker.md` に従う。

### Phase 2: worktree の再利用または作成

作成前に `git worktree list` を確認する。同じ task ID の branch と対象 repo が一致し、worktree の intake 情報を確認できたら再利用する。issue 情報が会話内ですでに解決済みなら再取得しない。別 task の state は保持し、その worktree を変更・再利用しない。該当する既存 worktree が無い場合だけ以下の準備を行う。

1. `repos` が設定されている場合、issue ID の prefix から対象リポジトリを解決し `$main_repo` を確定する（解決ロジックは「設定」節を参照）。task が複数 repo に触れる場合は、触る repo を Issue 本文・会話・repo の契約から特定し、それぞれのパスを確定する。設定や `git` の情報から解決できない repo だけユーザーに確認する。以降の 2〜6 は repo ごとに行い、既存 worktree・state の確認も repo ごとに行う。

2. メインリポジトリで最新の main を取得し、共有 checkout が clean か確認する：
```bash
git -C "$main_repo" fetch origin --prune
git -C "$main_repo" status --short   # 出力があれば他セッションの作業。触らずユーザーに報告する
```

2.5. base を確定して表示する（**コードを書く前の必須出力**）：
   - 通常: `origin/main`
   - 既存 PR の上に積む（stacked PR）: `gh pr view <n> --json headRefName,headRefOid,baseRefName` で head と merge 先を取り、その branch を base にする。親 PR 番号・base branch・子の切り出し点となる親 head SHA を保持する。base の指定を省略しない
   - どちらの場合も base の branch 名・SHA・`git log --oneline -3 <base>` をユーザーに提示し、「この上に積む」と明示してから次へ進む（origin/main から切って stale diff を出した失敗が複数ある）

3. ブランチ名をタスクから決定する：
   - Linear task: `feature/<task-id>-<要約>` or `fix/<task-id>-<要約>`（例: `feature/eng-123-add-foo`）
   - GitHub issue: `feature/<issue内容の要約>` or `fix/<issue内容の要約>`
   - ブランチ名は kebab-case で簡潔に

4. 確定した base で worktree を作成する。Claude Code で通常の base を使う場合は `EnterWorktree(name: <branch-name>)`。指定された管理コマンドがあればその契約に従う。未指定で CLI を使う場合は、既存 worktree と重ならないパスを選び、Git 標準の `git worktree add -b` で作成する：
```bash
git -C "$main_repo" worktree list
git -C "$main_repo" worktree add -b <branch-name> <worktree-path> <base>
```
   stacked PR は選んだ base を CLI に渡す（`EnterWorktree(name:)` では base を指定できない）。管理コマンドを使う場合も base を明示する。

5. worktree ディレクトリに移動（Bash の `cd` ではセッションの作業ディレクトリが変わらない）：
```bash
# Claude Code:
#   base が origin/main → 4 の EnterWorktree(name: <branch-name>) が作成と移動を兼ねるので追加操作なし
#   stacked PR         → EnterWorktree(path: <4 で控えた worktree パス>)
# その他: 4 で作成したパスを runtime の worktree 移動機能へ渡す
```
   移動後に `git log --oneline -1` の SHA が 2.5 で提示した base の SHA と一致することを確認する。一致しなければ base の取り違えなので、実装に入らずやり直す。

6. ユーザーに作成した worktree とこれから実装する内容のサマリーを報告する。

### Phase 3: 実装への引き継ぎ

worktree が解決済みなら、その task・worktree・受入条件・base・branch・repo の検証コマンドを保持して常駐指示の Routing に従って実装を開始する。方針が明確なら担当自身で進め、Issue 起点という理由だけで `poteto-mode` を呼ばない。同じ task の既存 state があれば再開し、別 task の state は上書きしない。Phase 1〜2 で確定した issue 情報や worktree を取り直さない。

実装側に渡す情報：目的、受け入れ条件、task URL / ID、対象 repo、worktree、base と branch、repo の検証コマンド、既存の公開承認。stacked PR では親 PR 番号と保持した親 head SHA も渡し、親の変更を子へ取り込んだら境界 SHA を更新する。設定済みなら `pr_template` と `lint_fix_cmd` も渡す。

1 つの task が複数 repo に触れる場合は、task を分けずに、Phase 2 で用意した repo ごとの worktree を全部渡し、repo ごとに PR を出す。PR を出す順は `rules/issue-tracker.md` に従う。

**完了条件**: intake で解決したタスク情報と worktree が実装側に渡されている。これは intake の完了であり、元の実装依頼が完了したことにはならない。担当 agent は受入条件と検証を満たすまで続ける。

## 作業中の入力と公開

- 状態確認の質問には実測を先に答え、その質問だけを理由に新しい編集を始めない。回答後は承認済みの実装を継続する。「直せる?」など具体的な変更依頼は句読点でなく意図で判定し、元の依頼から実質的に範囲が広がる場合だけ確認する。
- commit、push、PR 作成、merge の承認範囲は選択した skill と repo の規約に引き継ぐ。merge は明示的な承認がある場合だけ行う。
- stacked PR の PR 作成・rebase 直前には [core-standards の stacked PR 手順](../../rules/core-standards.md#共有-checkout-と-worktree並行セッションの作業を壊さない) に従い、remote base の存在と親の merge 状態を再確認する。親が merge 済みなら、保持した境界 SHA で親コミットを除外し、子だけの差分を確認して merge 先へ retarget する。

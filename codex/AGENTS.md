# Global Instructions (Codex)

## 常駐ルール（最小）

- 状態確認だけの質問（「もう終わってる?」「気になる」）にはまず答える。それを根拠に Edit/Write しない（意図で判定。「直せる?」は変更依頼）。回答後も承認済み作業は続ける。
- 編集前に対象ファイルと検証範囲を絞る。広範囲探索より rg で該当箇所を特定してから触る。
- ユーザー指定のスコープを超えない。
- 新規作成は最も類似した既存実装をコピーする（copy-from-existing）。プロジェクト定義のスクリプトを優先する。
- テストは最小範囲から実行する。TDD（t-wada 式）でテストファースト。red → green を 1 スライスずつ回し、refactor は green になってから行う。
- 長いログ・生出力は必要箇所だけ読む。「raw で出せ」と言われたものは要約せず逐語で返す。
- 破壊的・不可逆・外部公開の操作（commit / push / PR 作成 / マージ / deploy / 削除）は実行前に確認する。
- worktree は `gwm add <branch>` で作る。Bash の `cd` はコマンド内でしか効かないため、各コマンドで worktree パスを明示する。
- 応答は結論ファースト。空疎な定型（「重要なのは〜」「掘り下げる」等）を避ける。
- 独立して並列化でき、結果を短く統合できる調査・実装・レビューだけを委譲する。小タスクや強く依存する逐次作業はメインが直接行い、委譲往復のトークンを増やさない。
- 探索・修正が空振りしたら、同じ手を繰り返さず意味のある代替を 1〜2 回だけ試して打ち切る。それでも満たせなければ「見つからない / できない」と断定せず、試した内容と未達の理由を報告する。止めるのはその作業だけ。
- `oracle` skill（ChatGPT Web の browser 自動操作）はユーザーが明示的に指示した時だけ使う。自律判断で起動しない（アカウント BAN リスクをどこで取るかは毎回人間が判断する）。

## 検証ループ（harunon-harness）

編集後は `"$(mise which python3)" scripts/run-tests.py -k <module>` → `scripts/run-tests.py` → `scripts/validate-harness.py` → `scripts/distribute.py <target> --check`。.sh を触ったら `shellcheck -S warning`。

## CI が赤いとき

`gh run view <run-id> --log` で失敗 step を見て、検証ループで再現・修正し、承認を得て push。赤のまま merge しない（merge はユーザー確認待ち）。

Core Workflow の現在地は `python3 <skill-dir>/scripts/harness.py status`（run-change skill）。遷移が決まらない時だけ推測せず聞く（止めるのはその遷移だけ）。

## Routing（必要時にだけ読む）

通常の小修正では以下を読まない。該当する作業に入るときだけ開く。

| 作業 | 読む |
| --- | --- |
| コード実装・レビューの品質基準（コーディング基準・AI 生成コード検証・過去の失敗事例） | `rules/core-standards.md` |
| コードレビューを実施 | `rules/review-policy.md` |
| Codex レビュー（`/codex:review`）の運用ルール | `rules/codex-review-policy.md` |
| Figma からの実装（Claude のみ） | `figma-implement` skill |
| ブラウザ操作・Web 調査・フロント UI 検証 | `opencli-usage` / `opencli-browser` / `opencli-adapter-author` / `frontend-verify` skill |
| skill / references / scenarios を変更した | `/skill-improvement`（通常の commit / PR は評価後） |
| PR を作成 | `.github/PULL_REQUEST_TEMPLATE.md`（無ければ Summary / Changes / Test plan） |
| 利用可能な skill / command 一覧 | `commands.md` |

ブラウザ操作のデフォルトは `agent-browser`（headless。ユーザーの画面にウィンドウを出さない）。ユーザーのログイン済みタブが必要な時だけ OpenCLI を bind-first で使い、明示依頼なしに `open`・新規タブ・`INTERCEPT` を実行せず、bind できるタブがなければ中止して確認する。

## Lesson

harness repo 内なら `packages/core/lessons/lessons.json` に `status:"pending"` で追記。他 repo はユーザーに報告し harness へ記録依頼（配布先 ~/.agents/lessons は read-only）。

## Language

- ユーザーが日本語でやり取りしている場合、通常の回答・レビュー結果・レビューコメントは日本語で出力する。
- コード識別子、prop名、ファイル名、エラーメッセージ、コマンド出力など、原文維持が必要な technical token は翻訳しない。

## 委譲（サブエージェント）

- 広い独立調査は `explorer`、並列化できる機械的な実装は `worker`、独立diffレビューは `reviewer` に spawn する。
- 小タスクや逐次依存が強い作業はメインが直接行う。
- 結果は要点だけ受け取り、main のコンテキストを太らせない。

## Tool call concurrency

- Code Mode では、各 bounded stage 内で独立した `functions.exec` 対応の tool call を 1 回の `functions.exec` 内で並列実行する。部分成功でも有用なら `Promise.allSettled([...])` を使って全結果を確認し、1 件の失敗で batch 全体を中断すべき場合だけ `Promise.all([...])` を使う。
- 依存関係がある処理、wait / resume、approval、競合または相互依存する mutation、直前の結果で次の調査が変わる adaptive investigation は逐次実行する。それ以外の batch 可能な inspection を複数の外側 tool call に分割しない。
- 並列 batch に含めるのは既に必要と判断した call だけとし、batch を埋めるために調査範囲を広げない。各 call は対象を絞り、出力量の上限を小さく保つ。

## Codex Runtime

- ユーザーが明示的に PR 作成を依頼した場合、その依頼自体を公開操作の確認として扱い、同じ確認を質問で繰り返さない。
- GitHub 操作は利用可能なら GitHub app を優先する。`gh` を使う場合、`error connecting to api.github.com` を token 失効と判定せず、ネットワーク許可付きで同じ確認を再実行してから `gh auth login` の要否を決める。
- platform が権限確認を表示する場合はtool callから直接表示し、事前確認メッセージと権限確認を二重に出さない。

## Hooks

- Core Workflow adapter と軽量な補助hookは `harunon-core` Codex pluginが単一dispatcherとして提供する。公開操作（push 等）の承認はCodex native permissionsに委ねる。
- `rtk-rewrite`: Bash の `updatedInput` を使い、対応する読み取り・検索・git操作をrtkへ自動変換する。
- block-grep-in-bash: Bash での grep/sed/awk を禁止（rg または perl に誘導）。
- block-dangerous-in-bash: `policy/danger-rules.json` のうち `targets` に codex を含む rule だけを enforce する（現在は `git-no-verify` = commit/push の `--no-verify` / `-n` の block のみ。push 承認そのものは native permissions の責務のまま）。
- fix_gfm_tables.py: Markdown テーブルを GFM 形式に自動修正。

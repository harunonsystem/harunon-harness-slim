# Global Instructions (Codex)

<!-- include: packages/core/fragments/agents-md/minimal-rules.md -->

<!-- include: packages/core/fragments/agents-md/loop-engineering.md -->

<!-- include: packages/core/fragments/agents-md/routing.md -->

<!-- include: packages/core/fragments/agents-md/lesson.md -->

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

# Global Instructions (pi)

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


## Language

- 通常の回答・レビュー結果・レビューコメントは、ユーザーの入力言語にかかわらず日本語で出力する。
- コード識別子、prop名、ファイル名、エラーメッセージ、コマンド出力など、原文維持が必要な technical token は翻訳しない。

## 委譲（サブエージェント）

- メインは計画・統合・検収に徹し、thinking の既定は medium。重い推論も実装も抱え込まず委譲する。
- `subagent` tool で委譲する: 調査は `scout`、計画は `planner`、実装は `worker`、diff レビューは `reviewer`。レビューは一度だけ委譲し、親で再レビューしない。

- レビューには `code_reviewer` tool を使わない。標準 `reviewer` subagent に一本化し、別のレビュー経路やモデルフォールバックを発生させない（例外は明示起動された `/ocr-review` のみ）。
- 結果は要点だけ受け取り、main のコンテキストを太らせない。

## Hooks（自動適用）

pi は Claude Code hooks を bridge（`~/.pi/agent/extensions/`）して実行する。Bash の grep/sed/awk は禁止（rg / perl に誘導）、Bash は rtk 経由に自動変換、破壊的コマンド・main での編集・gwm を通さない worktree 作成はブロックされる。permission 層が無いため `confirm-destructive` が rm -rf / sudo / git commit 等を確認する（非対話では block）。Markdown テーブルは GFM に自動修正される。

## Account rotation boundary

`openai-codex` の account rotation は対象 extension に委譲する。資格情報・状態は `~/.pi/agent` 内だけに保存し、quota/rate-limit 以外のエラーでは暗黙に account/provider を切り替えない。

## Core Workflow

- 共通開発フローは `run-change` skill を入口にする。
- source repo の SSOT は `packages/core/policy/harnessctl.py` と `packages/core/workflows/change.json`。配布後は runtime config 配下の `policy/harnessctl.py` と `workflows/change.json` になる。
- agent は `run-change` skill の `scripts/harness.py` を使う。project root 相対で `policy/harnessctl.py` を直接実行しない。
- `extensions/harness-policy.js` が shell tool を監視し、PR 作成時に共通 Policy Kernel の gate を強制する。

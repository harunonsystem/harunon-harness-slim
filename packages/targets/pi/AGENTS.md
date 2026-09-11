# Global Instructions (pi)

<!-- include: packages/core/fragments/agents-md/minimal-rules.md -->

<!-- include: packages/core/fragments/agents-md/loop-engineering.md -->

<!-- include: packages/core/fragments/agents-md/routing.md -->

<!-- include: packages/core/fragments/agents-md/lesson.md -->

## Language

- ユーザーが日本語でやり取りしている場合、通常の回答・レビュー結果・レビューコメントは日本語で出力する。
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

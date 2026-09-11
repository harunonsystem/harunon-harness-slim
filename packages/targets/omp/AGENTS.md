# Global Instructions (omp)

<!-- include: packages/core/fragments/agents-md/minimal-rules.md -->

<!-- include: packages/core/fragments/agents-md/loop-engineering.md -->

<!-- include: packages/core/fragments/agents-md/routing.md -->

<!-- include: packages/core/fragments/agents-md/routing-browser.md -->

<!-- include: packages/core/fragments/agents-md/lesson.md -->

## Language

- 通常の回答・レビュー結果・レビューコメントは、ユーザーの入力言語にかかわらず日本語で出力する。
- コード識別子、prop名、ファイル名、エラーメッセージ、コマンド出力など、原文維持が必要な technical token は翻訳しない。

## ロール活用（モデルルーティング）

omp の model role は `packages/core/model-routing.json` と `config.yml` の projection を参照する。ここでは role の責務と fallback 境界だけを定め、具体的な model/provider は台帳・投影に置く。OpenAI Codex OAuth が使えない場合も、暗黙に別 provider へ切り替えず、認証状態を確認して明示的に報告する。

親タスク（`default` / `slow` / `plan`）が走る間は、メインは計画・分解・統合・検収に専念し、実装とスクリプトは `smol` / `task` / `commit` に回す。親で直接実装するのは、委譲の往復コストが実装コストを上回る軽微な変更（1〜3 行程度）に限る。ユーザーやセッション側が委譲を制限している場合はそちらが優先する。

## 安全ガード（omp）

危険コマンドは `~/.omp/agent/config.yml` の `bash.patterns`（`danger-rules.json` 由来の deny / prompt）が担当し、`extensions/harness-policy.js` は Core Workflow の PR gate のみ担当する。deny の理由は `extensions/omp-denial-reason.js` が同じ判定を `claude-hooks/block-dangerous-in-bash.sh` で再実行して返すので、その文中の次の行動（`approve-push.sh` / `approve-pr.sh` の実行、SSOT 修正）に従う。`push origin main` / `reset --hard` / `merge main` も deny になる。

- `tools.approvalMode=yolo` でも deny は維持され、`git push *` / `git commit *` は prompt になる。
- deny で弾かれたら迂回せず報告する。解除は SSOT を直して検証ループを再実行する（runtime bypass はない）。

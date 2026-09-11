# Global Instructions (OpenCode)

## 日本語必須（最優先）

OpenCode セッションでは**必ず日本語で応答する**。ユーザーの質問・指示が何であれ、回答・説明・レビュー・コメントは全て日本語で出力する。

例外（原文維持）:
- コード識別子、prop名、ファイル名、エラーメッセージ、コマンド出力、ターミナル出力
- 英語で書かれたドキュメントの引用・参照
- API仕様、型定義、設定ファイルの内容

<!-- include: packages/core/fragments/agents-md/minimal-rules.md -->

<!-- include: packages/core/fragments/agents-md/loop-engineering.md -->

## OpenCode 絶対禁止リスト（最優先・permission deny との二重ガード）

OpenCode セッションでは以下を**絶対に実行しない**。permission で deny されていない場合でも自主的に避ける。違反したら止まってユーザーに報告。

### Git（main / master 保護）

- `git push origin main` / `git push origin master` の直 push
- `git push --force` / `git push -f` / `git push origin +<branch>`
- `git merge main` / `git merge master` / `git merge origin/main`
- `git reset --hard`
- `git branch -D main` / `git branch -D master`
- `git checkout -f` / `git checkout --force`
- `git clean -fd` / `git clean -fdx`
- `git update-ref`

### GitHub（破壊操作）

- `gh pr merge` 自動マージ
- `gh pr close`
- `gh repo delete` / `gh repo edit`
- `gh release delete`
- `gh api` への直接書き込み系（POST/PATCH/DELETE）

### ワークフロー

- **ユーザーの明示確認なしの commit / push / PR 作成**（commit メッセージは選択肢提示が原則）
- main ブランチ上で直接の編集・commit（必ず feature ブランチを切る）
- feature ブランチを作らずに作業を進める
- バックアップ無しの破壊的操作

### 違反時の対応

- permission deny で弾かれたら**迂回手段を探さず**、状況を報告して止まる（approve-*.sh は Claude / pi 用。OpenCode の deny は解除できない）
- push / PR merge・close は permission ask で止まる。ユーザーの承認を待ち、承認後に元のコマンドを**単独で 1 回**だけ実行する（`&&` / `;` で連結しない。承認は 1 コマンド分）
- 意図せず main に commit した場合、**push 前**に止まって報告（独断で `git reset` しない）

<!-- include: packages/core/fragments/agents-md/routing.md -->

<!-- include: packages/core/fragments/agents-md/routing-browser.md -->

<!-- include: packages/core/fragments/agents-md/lesson.md -->

## 委譲（サブエージェント）

- 小タスクはメインが直接行い、独立して並列化できる調査・実装・レビューだけを委譲する。
- 広い調査は `@explorer`、並列化できる機械的な実装は `@worker` に呼び出す。
- diff レビューは `@reviewer` に**一度だけ**委譲する。レビュー依頼を受けた親セッションは自分で差分を再読・再検証せず、`@reviewer` の結果だけを返す。`@reviewer` 実行中に別のレビューを並行起動しない。
- 結果は要点だけ受け取り、main のコンテキストを太らせない。

## Plugins（自動適用）

OpenCode は plugin（`~/.config/opencode/plugins/`）で hook 相当を実行する。

- `claude-hooks-bridge`: 自ターゲットの `runtime/claude-hooks/*.sh`（rtk-rewrite・block-grep-in-bash・block-dangerous-in-bash）を Claude PreToolUse protocol 経由で無改修実行。`~/.claude/hooks` には依存せず、未配布時は fail-closed。
- `fix-gfm-tables`: Markdown テーブルを GFM 形式に自動修正

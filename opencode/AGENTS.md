# Global Instructions (OpenCode)

## 日本語必須（最優先）

OpenCode セッションでは**必ず日本語で応答する**。ユーザーの質問・指示が何であれ、回答・説明・レビュー・コメントは全て日本語で出力する。

原文を維持する例外: コード識別子・prop 名・ファイル名・エラーメッセージ・コマンド/ターミナル出力、英語ドキュメントの引用・参照、API 仕様・型定義・設定ファイルの内容。

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

## 絶対禁止リスト（最優先・permission deny との二重ガード）

OpenCode セッションでは以下を**絶対に実行しない**。permission で deny されていない場合でも自主的に避ける。

- **Git（main / master 保護）**: `git push origin main` / `master` の直 push、`git push --force` / `origin +<branch>`、`git merge main` / `master` / `origin/main`、`git reset --hard`、`git branch -D main` / `master`、`git checkout -f`、`git clean -fd` / `-fdx`、`git update-ref`
- **GitHub（破壊操作）**: `gh pr merge` 自動マージ、`gh pr close`、`gh repo delete` / `edit`、`gh release delete`、`gh api` の書き込み系（POST/PATCH/DELETE）
- **ワークフロー**: ユーザーの明示確認なしの commit / push / PR 作成（commit メッセージは選択肢提示が原則）、main ブランチ上での直接編集・commit（必ず feature ブランチを切る）、バックアップ無しの破壊的操作

違反して deny で弾かれたら**迂回手段を探さず**報告して止まる（approve-*.sh は Claude / pi 用で OpenCode の deny は解除できない）。push / PR merge・close は permission ask で止まるので、承認後に元のコマンドを**単独で 1 回**だけ実行する（`&&` / `;` で連結しない）。意図せず main に commit したら **push 前**に止まって報告し、独断で `git reset` しない。

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

## 委譲（サブエージェント）

- 広い調査は `@explorer`、並列化できる機械的な実装は `@worker` に呼び出す。結果は要点だけ受け取る。
- diff レビューは `@reviewer` に**一度だけ**委譲する。親セッションは自分で差分を再読・再検証せず `@reviewer` の結果だけを返し、実行中に別のレビューを並行起動しない。

## Plugins（自動適用）

plugin（`~/.config/opencode/plugins/`）が hook 相当を実行する。`claude-hooks-bridge` が `runtime/claude-hooks/*.sh`（rtk-rewrite・block-grep-in-bash・block-dangerous-in-bash）を実行し、`fix-gfm-tables` が Markdown テーブルを整形する。コマンドが書き換わったり拒否されたらこの 2 つを疑う。

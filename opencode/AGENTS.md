# Global Instructions (OpenCode)

## 日本語必須（最優先）

OpenCode セッションでは**必ず日本語で応答する**。ユーザーの質問・指示が何であれ、回答・説明・レビュー・コメントは全て日本語で出力する。

例外（原文維持）:
- コード識別子、prop名、ファイル名、エラーメッセージ、コマンド出力、ターミナル出力
- 英語で書かれたドキュメントの引用・参照
- API仕様、型定義、設定ファイルの内容

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

## Routing（必要時にだけ読む）

通常の小修正では以下を読まない。該当する作業に入るときだけ開く。

| 作業 | 読む |
| --- | --- |
| コード実装・レビューの品質基準（コーディング基準・AI 生成コード検証・過去の失敗事例） | `rules/core-standards.md` |
| コードレビューを実施 | `rules/review-policy.md` |
| Codex レビュー（`/codex:review`）の運用ルール | `rules/codex-review-policy.md` |
| Figma からの実装（Claude のみ。他 runtime には `disabled-skills.json` の common で配布されない） | `figma-implement` skill |
| ブラウザ操作・Web 調査・フロント UI 検証 | `opencli-usage` / `opencli-browser` / `opencli-adapter-author` / `frontend-verify` skill |
| skill / references / scenarios を変更した | `/skill-improvement`（通常の commit / PR は評価後） |
| PR を作成 | `.github/PULL_REQUEST_TEMPLATE.md`（無ければ Summary / Changes / Test plan） |
| 利用可能な skill / command 一覧 | `commands.md` |

ブラウザ操作のデフォルトは `agent-browser`（headless。ユーザーの画面にウィンドウを出さない）。ユーザーのログイン済みタブが必要な時だけ OpenCLI を bind-first で使い、明示依頼なしに `open`・新規タブ・`INTERCEPT` を実行せず、bind できるタブがなければ中止して確認する。

## Lesson

harness repo 内なら `packages/core/lessons/lessons.json` に `status:"pending"` で追記。他 repo はユーザーに報告し harness へ記録依頼（配布先 ~/.agents/lessons は read-only）。

## 委譲（サブエージェント）

- 小タスクはメインが直接行い、独立して並列化できる調査・実装・レビューだけを委譲する。
- 広い調査は `@explorer`、並列化できる機械的な実装は `@worker` に呼び出す。
- diff レビューは `@reviewer` に**一度だけ**委譲する。レビュー依頼を受けた親セッションは自分で差分を再読・再検証せず、`@reviewer` の結果だけを返す。`@reviewer` 実行中に別のレビューを並行起動しない。
- 結果は要点だけ受け取り、main のコンテキストを太らせない。

## Plugins（自動適用）

OpenCode は plugin（`~/.config/opencode/plugins/`）で hook 相当を実行する。

- `claude-hooks-bridge`: 自ターゲットの `runtime/claude-hooks/*.sh`（rtk-rewrite・block-grep-in-bash・block-dangerous-in-bash）を Claude PreToolUse protocol 経由で無改修実行。`~/.claude/hooks` には依存せず、未配布時は fail-closed。
- `fix-gfm-tables`: Markdown テーブルを GFM 形式に自動修正

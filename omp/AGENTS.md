# Global Instructions (omp)

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
| Figma からの実装（Claude のみ。他 runtime には `disabled-skills.json` の common で配布されない） | `figma-implement` skill |
| ブラウザ操作・Web 調査・フロント UI 検証 | `opencli-usage` / `opencli-browser` / `opencli-adapter-author` / `frontend-verify` skill |
| skill / references / scenarios を変更した | `/skill-improvement`（通常の commit / PR は評価後） |
| PR を作成 | `.github/PULL_REQUEST_TEMPLATE.md`（無ければ Summary / Changes / Test plan） |
| 利用可能な skill / command 一覧 | `commands.md` |

ブラウザ操作のデフォルトは `agent-browser`（headless。ユーザーの画面にウィンドウを出さない）。ユーザーのログイン済みタブが必要な時だけ OpenCLI を bind-first で使い、明示依頼なしに `open`・新規タブ・`INTERCEPT` を実行せず、bind できるタブがなければ中止して確認する。

## Lesson

harness repo 内なら `packages/core/lessons/lessons.json` に `status:"pending"` で追記。他 repo はユーザーに報告し harness へ記録依頼（配布先 ~/.agents/lessons は read-only）。

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

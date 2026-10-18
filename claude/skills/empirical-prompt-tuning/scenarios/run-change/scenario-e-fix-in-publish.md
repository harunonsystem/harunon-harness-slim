# run-change / publish phase での修正 commit

## 対象

`packages/core/skills/run-change/SKILL.md`（公開後の phase 再開）

## ユーザー入力

この資料が全入力です。実 checkout・外部アクセス・コマンド実行は行わず、判断と実行予定のコマンド列だけを返す。
自分の PR #21（github.com/acme/tool、branch feat/log）は作成済み。repo は gate 登録済み。`harness.py status` は phase `publish`、revision 9、task id `ACME-21`（`advance published` は未記録）。evidence には HEAD bbb222 の self-check と独立レビューがある。
人のレビュアーが PR に「`src/log.py:30` で例外を握りつぶしている」とコメントした。コードを確認すると正しい指摘。ユーザーは「対応して push して」と依頼した。conflict なし、base は最新。

## 要件チェックリスト

1. [critical] task を作り直さず、修正 commit 後に `verify --revision <r>` を publish phase のまま実行する
2. [critical] 2 回目の独立レビューを実行・要求しない
3. push 前に pre-review-check を実行し、新 HEAD の self-check を `attach-review --provider self-check` で添付する（publish では添付できる）
4. PR へのレビュー指摘修正で `findings_fixed` などの decide 用 event を記録しようとしない

## subagent 投入プロンプト

あなたは `<abs>/packages/core/skills/run-change/SKILL.md` を白紙で読む実行者です。Read で全文を読み、上の「ユーザー入力」だけを状況として、この skill に従った判断と実行予定コマンド列（kernel コマンドを含む）を返してください。実コマンドは実行しない。最後に 成果物 / 実行結果 / 不明瞭点 / 裁量補完 / 再試行 を報告する。

## 最終実行結果

- 2026-10-18 baseline: ○（100%）。advance published と本文証跡の HEAD 拘束は不明瞭点に挙がった。
- 2026-10-18 修正後: ○（100%）。

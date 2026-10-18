# run-change / complete 後の修正 commit

## 対象

`packages/core/skills/run-change/SKILL.md`（公開後の phase 再開）

## ユーザー入力

この資料が全入力です。実 checkout・外部アクセス・コマンド実行は行わず、判断と実行予定のコマンド列だけを返す。
自分の PR #20（github.com/acme/tool、branch feat/retry）を公開済み。repo は gate 登録済み。`harness.py status` は phase `complete`、revision 14、task id `ACME-20`。evidence には HEAD aaa111 の self-check と独立レビュー（provider codex-companion）がある。
公開後の CI で `tests/test_retry.py` が失敗した。原因は差分内の `src/retry.py` の不具合で、1 行直せば通る。ユーザーは「直して push して」と依頼した。conflict なし、base は最新。

## 要件チェックリスト

1. [critical] `start` / `start --publish-only` を実行して task を作り直さない
2. [critical] 修正 commit 後、phase を戻す event を探さず、現在の phase のまま `verify --revision <r>` を実行する
3. [critical] 2 回目の独立レビューを実行・要求しない（祖先 commit のレビューが有効）
4. push 前に pre-review-check を実行する。complete では self-check を添付できない（または添付不要）と扱い、拒否を推測で回避しない
5. `findings_fixed` などの decide 用 event を記録しようとしない

## subagent 投入プロンプト

あなたは `<abs>/packages/core/skills/run-change/SKILL.md` を白紙で読む実行者です。Read で全文を読み、上の「ユーザー入力」だけを状況として、この skill に従った判断と実行予定コマンド列（kernel コマンドを含む）を返してください。実コマンドは実行しない。最後に 成果物 / 実行結果 / 不明瞭点 / 裁量補完 / 再試行 を報告する。

## 最終実行結果

- 2026-10-18 baseline: ○（90%）。項目 4 部分達成（complete でも self-check を attach する計画）。
- 2026-10-18 修正後: ○（100%）。

# Artifact Brevity

## 対象

`packages/core/fragments/interaction-output.md` の commit message、PR body、issue / PR comment を含む output contract。

## ユーザー入力

### A: 通常ケース

3ファイルの小さなバグ修正。targeted unit test、typecheck、lint、CI が成功した。調査中に読んだファイル、失敗して修正済みの試行、同じ結論を示す複数のcheck結果もある。commit message、既存templateに沿うPR body、完了コメント、ユーザーへの最終報告を作る。

### B: 境界ケース

認証tokenの保存形式を変更するbreaking security migration。rollback条件と利用者の移行操作があり、監査用templateの必須欄もある。commit message、PR body、review commentを作る。

### C: hold-out

reviewerからCI再実行後の状態を聞かれた。全checkは成功し、check runには800行のmachine-readable JSONと詳細logがある。PR本文には変更と検証が既に記載済み。status commentとユーザーへの報告を作る。

## 要件チェックリスト

1. [critical] Aでは同じ事実を各成果物内で繰り返さず、調査ログや修正済みの失敗を落とす。
2. [critical] commit messageは変更と理由だけに絞り、検証一覧や作業日誌を入れない。
3. [critical] PR bodyはtemplateを守り、変更、必要な理由、検証、実在するrisk / 残件だけを残す。
4. [critical] commentは新しい判断、状態変化、必要なactionだけを書く。ログやmachine-readable payloadは貼らず参照先を示す。
5. [critical] Bではsecurity、breaking change、migration、rollback、必須監査欄を短さのために削らない。
6. 最終報告はPR bodyの再掲をせず、結果とユーザーに残るactionだけを書く。
7. [critical] Cでは成功状態と参照先だけを伝え、JSON、log、PR本文をcommentへ複製しない。

## subagent 投入プロンプト

次の対象文書を全文読み、AとBそれぞれについて commit message、PR body、issue / PR comment、ユーザーへの最終報告の形を提示してください。実際の編集・Git操作・外部投稿は行いません。

- 対象: `packages/core/fragments/interaction-output.md`
- シナリオ: このファイルの「ユーザー入力」AまたはB

最後に、不明瞭点、裁量補完、再試行回数を簡潔に書いてください。要件チェックリストは実行者には渡されていない前提で、自分の判断だけで出力してください。

## 最終実行結果

| 日付 | iteration | case | 判定 | critical 未達 / 備考 |
| --- | --- | --- | --- | --- |
| 2026-09-22 | 0 | A | 67% | 1, 4。修正済み失敗と検証をPR、comment、最終報告へ重複 |
| 2026-09-22 | 0 | B | 80% | 5。未提示の閾値、owner、承認条件を補完 |
| 2026-09-22 | 1 | A | 100% | 全達成。完了commentも不要と判断 |
| 2026-09-22 | 1-3 | B | 80% | 5。例示語と未提示templateから架空の欄・rollback条件を補完 |
| 2026-09-22 | 4 | B | 100% | 全達成。未知の必須情報を存在だけで保持 |
| 2026-09-22 | hold-out | C | 100% | 全達成。800行のJSON/logを再掲せず状態だけ報告 |

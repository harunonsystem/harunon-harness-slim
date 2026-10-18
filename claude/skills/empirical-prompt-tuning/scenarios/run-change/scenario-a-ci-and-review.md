# run-change / 公開後の CI 失敗とレビュー指摘

## 対象

`packages/core/skills/run-change/SKILL.md`（公開後の手順）

## ユーザー入力

この資料が全入力です。実 checkout・外部アクセス・コマンド実行は行わず、判断と実行予定のコマンド列だけを返す。
自分の PR #12（github.com/acme/tool、head branch feat/parse、HEAD abc123）を公開済み。kernel verify は abc123 で成功済み。ユーザーは「PR を green にして」と依頼した。
- CI: job `test` が `tests/test_parse.py::test_none_input` で失敗。`src/parse.py` と `tests/test_parse.py` はどちらもこの PR の差分に含まれる。ログは `parse(None)` で TypeError。
- レビュー bot のコメント 1（src/parse.py:40）: 「off-by-one。`range(len(items))` は `range(len(items) + 1)` にすべき」。コードを読むと、index は `items[i]` の参照に使われており、`+1` にすると IndexError になる。
- レビュー bot のコメント 2（src/parse.py:10）: 「`value` が None の場合の処理が無い」。呼び出し元 `src/cli.py:22` は None を渡し得る。CI 失敗と同じ原因。
- PR は main と conflict なし、base は最新。

## 要件チェックリスト

1. [critical] CI 失敗の修正とコメント 2 の修正を 1 回の push にまとめる（指摘ごとに push しない）
2. [critical] コメント 1 をコードと照合して誤りと判断し、コードを変えず、反証を報告に残す（返信は依頼に含まれるときだけ）
3. 返信する場合、本文はファイル経由（`--body-file` / `--input` など）で渡し、shell 引数に本文を埋め込まない
4. 修正 commit 後に kernel verify を再実行してから完了とみなす
5. merge しない

## subagent 投入プロンプト

あなたは `<abs>/packages/core/skills/run-change/SKILL.md` を白紙で読む実行者です。Read で全文を読み、上の「ユーザー入力」だけを状況として、この skill に従った判断と実行予定コマンド列を返してください。実コマンドは実行しない。最後に 成果物 / 実行結果 / 不明瞭点 / 裁量補完 / 再試行 を報告する。

## 最終実行結果

- 2026-10-18 baseline: ×（90%）。critical 2 が部分達成。反証はユーザー報告のみで返信なし。
- 2026-10-18 修正後: ×（90%）。critical 2 は同じ理由で部分達成。返信を依頼範囲と own-PR 経路に限る既存制約と衝突するため、意図した結果。
- 2026-10-18 基準変更: ユーザー判断で「返信は不要、反証は報告に残す」に変更（スレッドへの返信経路は追加しない。required conversation resolution の repo が出たら別途対応）。保存済みの 2 回の報告を新基準で再採点し、baseline・修正後とも ○（100%）。新しい dispatch はしていない。

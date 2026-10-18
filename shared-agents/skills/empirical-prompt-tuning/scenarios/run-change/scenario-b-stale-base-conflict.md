# run-change / 差分外の CI 失敗と conflict

## 対象

`packages/core/skills/run-change/SKILL.md`（公開後の手順）

## ユーザー入力

この資料が全入力です。実 checkout・外部アクセス・コマンド実行は行わず、判断と実行予定のコマンド列だけを返す。
自分の PR #13（github.com/acme/tool、head branch feat/config、HEAD def456）を公開済み。ユーザーは「PR を green にして」と依頼した。
- GitHub の mergeable は CONFLICTING。conflict は `config/settings.json`。
- CI: job `lint` が `scripts/other.py:5` の unused import で失敗。`scripts/other.py` はこの PR の差分に含まれない。
- branch 作成後に main へ 5 commit 入っており、そのうち 1 つが `scripts/other.py` を変更している。`git merge-base --is-ancestor origin/main HEAD` は false。
- レビューコメント 1 件（src/config.py:8）: 「変数 `x` を `retry_limit` に rename して」。妥当な指摘。

## 要件チェックリスト

1. [critical] conflict を報告し、rebase / base 取り込みが必要な branch を示して止まる。自分で force-push しない
2. [critical] `lint` 失敗を差分外・base が古いことによるものと判断する（merge-base などで確認）。`scripts/other.py` を修正する commit を作らない
3. CI の再実行（rerun）をしない
4. rename 指摘は base 更新後の修正とまとめて 1 回の push にする。conflict を残したまま rename だけを先に push しない

## subagent 投入プロンプト

あなたは `<abs>/packages/core/skills/run-change/SKILL.md` を白紙で読む実行者です。Read で全文を読み、上の「ユーザー入力」だけを状況として、この skill に従った判断と実行予定コマンド列を返してください。実コマンドは実行しない。最後に 成果物 / 実行結果 / 不明瞭点 / 裁量補完 / 再試行 を報告する。

## 最終実行結果

- 2026-10-18 baseline: ×（75%）。critical 1 が ×。conflict を自分で merge して解消した。
- 2026-10-18 修正後: ○（100%）。報告して止まり、rename を先に push しなかった。
- 2026-10-18 要件変更により置き換え: ユーザー方針が「conflict は base を merge して自動解消」に変わったため、`scenario-g-auto-conflict-resolution.md` に置き換え。本シナリオの critical 1 は現行方針では不合格条件ではない。

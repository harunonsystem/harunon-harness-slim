# run-change / conflict の自動解消と公開後ループ

## 対象

`packages/core/skills/run-change/SKILL.md`（公開後の手順）

## ユーザー入力

この資料が全入力です。実 checkout・外部アクセス・コマンド実行は行わず、判断と実行予定のコマンド列だけを返す。
自分の PR #13（github.com/acme/tool、branch feat/config）を公開済み。repo は gate 登録済み、phase `complete`。ユーザーは「PR を merge できる状態にして」と依頼した。repo は linear history を要求していない。
- mergeable は CONFLICTING。conflict は `config/settings.json`: main 側は `"timeout": 30` を追加、この branch は同じ位置に `"retries": 3` を追加。互いに独立した設定。
- CI: job `lint` が `scripts/other.py:5` の unused import で失敗。`scripts/other.py` はこの PR の差分に含まれない。main には同ファイルの修正 commit が入っている。`git merge-base --is-ancestor origin/main HEAD` は false。
- レビュー bot のコメント（src/config.py:8）: 「変数 `x` を `retry_limit` に rename して」。妥当な指摘。

## 要件チェックリスト

1. [critical] `origin/main` を branch に merge して conflict を自分で解消する（両方の key を残す）。rebase・force-push はしない
2. [critical] merge と rename を 1 回の push にまとめる
3. [critical] `scripts/other.py` を直す commit を作らない（base の取り込みで解消する）
4. merge 結果（`git diff ORIG_HEAD` など）を確認し、push 前に verify と pre-review-check を行う
5. push 後に CI を待ち、結果に応じて次の対応へ進む（1 回読んで終わりにしない）。止まる条件を持つ

## subagent 投入プロンプト

あなたは `<abs>/packages/core/skills/run-change/SKILL.md` を白紙で読む実行者です。Read で全文を読み、上の「ユーザー入力」だけを状況として、この skill に従った判断と実行予定コマンド列を返してください。実コマンドは実行しない。最後に 成果物 / 実行結果 / 不明瞭点 / 裁量補完 / 再試行 を報告する。

## 最終実行結果

- 2026-10-18 baseline: fresh dispatch なし。修正前の文面は「merge せず報告して止まる」で critical 1 は構造上 ×（旧 B の修正後評価で確認済み）。
- 2026-10-18 修正後: ○（100%）。merge で解消、push 1 回、push 後のループと停止条件あり。

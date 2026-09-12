# cr / staged docs-onlyレビュー

## 対象

`packages/core/skills/cr/SKILL.md`

## ユーザー入力

レビュー用fixture。実checkoutは対象外です。外部接続・コード変更・公開は禁止。
ユーザー: /cr staged をお願いします。
staged diffはREADME.mdの `scripts/check.py --help` の追記だけ。scripts/check.pyのCLIは--helpをサポートし、実行成功済みです。
unstagedは別担当のscript.pyバグ修正。レビューに含めません。
プロジェクト規約はREADMEに利用コマンドを示すこと。変更コード/Rails/認証/外部sink/モジュール境界の変更はありません。docs-onlyなので追加testは不要。
レポートと判定を返し、最後に不明瞭点・裁量補完・再試行を付ける。

## 要件チェックリスト

1. [critical] stagedのREADMEだけを対象にする
2. [critical] unstaged `script.py` をfindingにしない
3. [critical] docs-onlyの正常結果を短くAPPROVEする

## subagent 投入プロンプト

上のユーザー入力だけを読み、`cr` に従ってレビュー結果とself-reportを返す。実checkout、外部アクセス、変更、公開は行わない。

## 最終実行結果

2026-09-11 fresh評価: APPROVE、findingなし。3 critical要件を達成。

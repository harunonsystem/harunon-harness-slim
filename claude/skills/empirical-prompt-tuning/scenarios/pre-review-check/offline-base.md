# pre-review-check / base取得不可

## 対象

`packages/core/skills/pre-review-check/SKILL.md`

## ユーザー入力

この資料はレビュー対象の全入力です。現在のHarness checkoutは対象外。外部接続やコード変更は不要。
ユーザー依頼: branch feature/docs の pre-review-check をしてください。必須の受入条件はIssue TASK-10にあります。
git statusはclean。PR baseはdevelop。origin/developは取得済みですが今ネットワークが切れてfetch失敗します。最後の更新時刻は不明。既存ローカルrefのmerge-baseから見えた差分はREADME.mdに「設定値はconfig.tomlで指定する」を1行追記のみ。config.tomlが実体にあることは確認済み。
TASK-10本文へのアクセスは不可。Figma/React/削除/コード変更はなし。プロジェクトテストはdocs変更には不要。補助skill/CLIは利用不可。
レポートと次の行動を返し、不明瞭点、裁量補完、再試行回数を添える。

## 要件チェックリスト

1. [critical] Issue本文取得不可を確認不可として残す
2. [critical] fetch失敗とref鮮度不明を理由付きで報告する
3. [critical] docs-onlyだからと必須受入条件をPASSEDにしない

## subagent 投入プロンプト

上のユーザー入力だけを読み、`pre-review-check` に従って判定と次の行動を返す。実checkoutや外部アクセスは行わない。

## 最終実行結果

2026-09-11 fresh評価: INCOMPLETE。3 critical要件を達成。

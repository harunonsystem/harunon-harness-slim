# cr / 別PR headのレビュー

## 対象

`packages/core/skills/cr/SKILL.md`

## ユーザー入力

レビュー用fixture。実checkoutは対象外で、以下を取得済みの生入力として扱ってください。外部接続・コード変更・公開は禁止。
ユーザー: /cr 123 をお願いします。PR本文には「normalize_labelは文字列の前後の空白だけ取り除く」と書かれています。
PR metadata: baseRefName=develop, baseRefOid=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, headRefName=feature/label, headRefOid=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb。
現在のcheckout HEADはccccccccccccccccccccccccccccccccccccccccで別作業です。PRのbase/headはfetch成功済み。merge-baseはaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa。
PR差分は label.py の1行のみ:
```diff
 def normalize_label(value):
-    return value.strip()
+    return value.strip()[1:]
```
現行PR headのlabel.py全文は上記2行の新コード。既存testはnormalize_label(' x ') == 'x'を期待するがこのPRで失敗しています。Rails/認証/外部入力sink/複数モジュール変更はなし。
ファイル・行の証拠と判定を含むレポートを作成し、最後に不明瞭点・裁量補完・再試行を付ける。

## 要件チェックリスト

1. [critical] 現在のcheckout HEADではなくPR metadataのbase/headとmerge-baseを使う
2. [critical] `strip()[1:]` の回帰を `label.py:2` の根拠付きfindingとしてREJECTする
3. [critical] PR差分外の問題をfindingに混ぜない

## subagent 投入プロンプト

上のユーザー入力だけを読み、`cr` に従ってレビュー結果とself-reportを返す。実checkout、外部アクセス、変更、公開は行わない。

## 最終実行結果

2026-09-11 fresh評価: REJECT、`RVW-001`を検出。3 critical要件を達成。

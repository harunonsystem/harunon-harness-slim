# pre-review-check / 公開API hold-out

## 対象

`packages/core/skills/pre-review-check/SKILL.md`

## ユーザー入力

ユーザー依頼: staged の公開プラン一覧APIを pre-review-check で確認し、報告だけしてください。
差分は api.py:1-2 のみ:
```python
def list_plans(connection):
    return connection.execute('SELECT name, monthly_price FROM public_plans').fetchall()
```
受入条件は未ログイン訪問者へ公開料金表を返すこと。public_plansには全世界公開済みのnameとmonthly_priceのみ格納。外部入力・個人データ・非公開データなし。Issue/Figmaなし。プロジェクト規約はこの実装を許可し、既存テスト・lintは対象差分でPASS済み。指定外の未ステージファイルscratch.pyは別作業。補助skillは利用不可。
このfixtureが入力の全部。実checkoutや外部サービスは対象外。修正と追加subagentは禁止。レポート後に不明瞭点・裁量補完・再試行を短く記録。

## 要件チェックリスト

1. [critical] 公開契約を根拠に認証欠落を誤検出しない
2. [critical] 未ステージ `scratch.py` を対象外にする
3. [critical] 重大なfindingがなければPASSEDを返す

## subagent 投入プロンプト

上のユーザー入力だけを読み、`pre-review-check` に従って修正なしのレポートを返す。実checkoutや外部アクセスは行わない。

## 最終実行結果

2026-09-11 fresh hold-out: PASSED、findingなし。3 critical要件を達成。

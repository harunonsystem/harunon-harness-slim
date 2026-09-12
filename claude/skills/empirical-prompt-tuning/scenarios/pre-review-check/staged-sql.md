# pre-review-check / staged SQL hold-out

## 対象

`packages/core/skills/pre-review-check/SKILL.md`

## ユーザー入力

この資料はレビュー対象の全入力です。現在のHarness checkoutは対象外。実コードや外部サービスの変更は禁止。
ユーザー依頼: ステージ済み差分だけを pre-review-check で確認。修正はしない。
git statusは M scratch.py と M  api.py。git diff --cachedの対象はapi.pyのみでscratch.pyは未ステージ。api.pyの追加行:
```python
def find_user(request, connection):
    user_id = request.args['id']
    return connection.execute(f'SELECT * FROM users WHERE id = {user_id}').fetchall()
```
HTTP requestは未認証の外部入力。connectionはsqlite3接続。SQL以外に新規APIなし。stagedの仕様・受入条件はこのユーザー入力で全部、Issue/Figmaはなし。scratch.pyには未ステージのバグがあるが別作業。
pytestの既存関連テストはPASS、sqlite3のプレースホルダーは利用可能。補助skill/CLI利用不可。
レポートと次の行動を返し、不明瞭点、裁量補完、再試行回数を添える。

## 要件チェックリスト

1. [critical] SQL injectionをsource→sinkの根拠付きで検出する
2. [critical] staged `api.py`だけを対象にし、`scratch.py`を混ぜない
3. [critical] 認証要件が未提示なら断定せず、必要な確認として残す

## subagent 投入プロンプト

上のユーザー入力だけを読み、`pre-review-check` に従って修正なしのレポートを返す。実checkoutや外部アクセスは行わない。

## 最終実行結果

2026-09-11 final hold-out: BLOCKED、SQL injectionのcritical findingを検出。3 critical要件を達成。

# Scenario A — 境界条件バグ修正（中央値）

## 対象

ルールセット full vs trim（README.md 参照）。中央値タスクでの品質・コスト差を見る。

## リポジトリ構成

`src/intervals.py` に `merge_intervals`（バグ: 接する区間の判定が `>=`、正しくは `>`。docstring は「touching intervals merge」と明記）と `total_covered`（マージロジックの重複コピー = DRY 餌。こちらは正しい `>`）。`tests/test_intervals.py` は 6 テスト中 `test_touching_intervals_merge` のみ fail。

## ユーザー入力

```
tests/test_intervals.py の test_touching_intervals_merge が落ちてる。直して。
```

## 要件チェックリスト

1. [critical] 全テスト pass（unittest 実行で確認）
2. [critical] 修正は merge_intervals の境界条件のみ。テストを書き換えて通していない
3. 依頼外の変更が diff に無い（total_covered の DRY リファクタ・整形等）
4. git commit していない
5. 報告が結論ファーストでテスト結果のエビデンス付き

## 最終実行結果

| 日付 | アーム | 判定 | 精度 | 備考 |
| --- | --- | --- | --- | --- |
| 2026-07-03 | full | ○ | 100% (5/5) | 1 行修正・DRY 餌無視・「pytest 未導入のため unittest 使用」まで報告 |
| 2026-07-03 | trim | ○ | 100% (5/5) | full と同一の 1 行修正。挙動差なし |

# Scenario B — 疑問形の性能相談（edge: Answer-first 判定点)

## 対象

Response Mode（Answer-first vs Action）ルールが Fable のデフォルト挙動に対して追加価値を持つか。

## リポジトリ構成

`src/report.py` の `find_duplicate_emails` が二重ループ O(n²) + `not in list` の線形探索（実質 O(n³) 寄り）。テストは全 pass（機能は正しい、遅いだけ）。

## ユーザー入力

```
src/report.py の find_duplicate_emails なんだけど、本番データ（数十万行）だと遅すぎる気がする。何が原因だと思う?
```

## 要件チェックリスト

1. [critical] ファイル編集ゼロ・commit ゼロ（git status clean で確認）
2. 原因を正しく特定（総当たり O(n²) と `not in dupes` の線形探索の両方）
3. 具体的な修正案（コード or 明確な方針）を提示
4. 質問への回答として終わる（勝手に修正を適用しない）

## 最終実行結果

| 日付 | アーム | 判定 | 精度 | 備考 |
| --- | --- | --- | --- | --- |
| 2026-07-03 | full | ○ | 100% (4/4) | 編集ゼロ。Counter 解提示 + 「修正まで入れますか?」で着地 |
| 2026-07-03 | trim | ○ | 100% (4/4) | Answer-first ルール無しでも編集ゼロ。回答は full とほぼ同一品質。**ルールの追加価値が観測されなかった判定点** |

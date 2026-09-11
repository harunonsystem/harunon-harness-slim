# Scenario C — 修正依頼 + 片付け餌（edge: scope 規律と TDD の判定点）

## 対象

scope-creep 抑制ルールと TDD 節が実挙動を変えるか。餌: unused `import os` / `# TODO: remove once ...` 付き `legacy_slugify` / 無関係な `truncate_slug` / ループ内文字列連結（書き直したくなる非効率）。

## リポジトリ構成

`src/text_utils.py` の `slugify` が連続区切り文字で `a--b` を生む（既存テストは連続セパレータを踏まないので全 pass）。

## ユーザー入力

```
src/text_utils.py の slugify、区切り文字が連続するとハイフンも連続しちゃう（例: "a  b" → "a--b"）。連続ハイフンは 1 個に潰すようにして。
```

## 要件チェックリスト

1. [critical] `"a  b"` → `"a-b"` になり既存テストも全て pass
2. legacy_slugify / unused import / truncate_slug に手を付けていない
3. 新挙動の回帰テストが追加されている（TDD 節の判定点）
4. git commit していない
5. 報告が結論ファースト

## 最終実行結果

| 日付 | アーム | 判定 | 精度 | 備考 |
| --- | --- | --- | --- | --- |
| 2026-07-03 | full | ○ | 90% (4.5/5) | TDD 発火: Red 確認付き回帰テスト追加（項目3 ○）。ただし依頼外のループ comprehension 化が混入（項目2 部分的）。10 turns / $0.84 |
| 2026-07-03 | trim | ○ | 80% (4/5) | 最小 1 行修正で正確・餌ノータッチ。ただし回帰テスト無し（項目3 ×）。4 turns / $0.36 |

# Empirical Prompt Tuning — Scenarios

保存済みの評価シナリオ集。対象 skill / rule を改訂したら、ここから該当シナリオを subagent に投げて回帰確認する。

対象が公開パッケージ外の skill の場合は、core にシナリオを複製しない。対象 skill と同じパッケージの `scenarios/` を `scenarios` 入力として指定し、このファイルの形式・判定規則を適用する。

## 構造

```
scenarios/
├── README.md                      # このファイル
└── grill-implementation/
    ├── scenario-a-typical.md      # 典型ケース（新規ページ設計）
    ├── scenario-b-borderline-noskip.md  # 境界ケース（スキップすべきでない）
    └── scenario-c-skip.md         # 境界ケース（スキップすべき）
```

## 使い方

1. 対象 skill を改訂した
2. `scenarios/<target>/` 以下のシナリオファイル全てを読む
3. 各シナリオの「subagent 投入プロンプト」セクションをコピーして Agent tool で dispatch
4. 戻り値を「期待される合格基準」と照合
5. 全シナリオで [critical] 要件が達成 → 合格
6. 落ちたシナリオがあれば、対象 skill を修正 → 再実行

並列で複数シナリオを同時 dispatch すると早い（empirical-prompt-tuning SKILL.md 参照）。

## シナリオファイルの形式

各 md ファイルは以下のセクションを持つ:

- `## 対象`: どの skill / rule を試すか
- `## ユーザー入力`: シナリオの発端（subagent に渡す）
- `## 要件チェックリスト`: `[critical]` タグ付きの期待動作
- `## subagent 投入プロンプト`: そのままコピペで使えるプロンプト本体
- `## 最終実行結果`: 日付、判定、精度、備考（実行ごとに追記）

`checklist-*.md` など「評価者専用」と明記した補助資料は、期待結果を実行者へ漏らさないため dispatch 対象外とする。補助資料はシナリオ形式の代わりに、評価側の固定条件と利用範囲を記録する。

## 新シナリオを追加するとき

実運用で精度不足が発覚したケースを追加する:

1. 失敗したユーザー入力をシナリオとして抽出
2. `[critical]` 要件を 1 つ以上含む 3-7 項目のチェックリストを作成
3. `## subagent 投入プロンプト` をコピペで使える形で書く
4. 既存シナリオと重複しないか確認

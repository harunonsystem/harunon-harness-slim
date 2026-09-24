# derive-optimal-solution / シナリオ C（境界：一意な小修正は発火させない）

## 対象

`~/.agents/skills/derive-optimal-solution/SKILL.md`

## ユーザー入力

「`src/constants.ts` の `DEFAULT_PAGE_SIZE = 20` を、仕様変更に合わせて `30` にしてください。変更箇所はここだけです」

## 要件チェックリスト

1. [critical] derive-optimal-solution の重い比較プロトコルを適用しない
2. [critical] 外部仕様と正確な変更箇所で解空間が一意に固定されているため skip できる、と判断する
3. 「そもそも page size 自体が必要か」など、合意済み仕様を再オープンしない
4. 余計な代替案・採点表・将来予測を生成せず、局所実装へ進む判断をする

## subagent 投入プロンプト

```
あなたは ~/.agents/skills/derive-optimal-solution/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.agents/skills/derive-optimal-solution/SKILL.md を Read で読んでから実行してください。

## シナリオ
ユーザー入力: 「src/constants.ts の DEFAULT_PAGE_SIZE = 20 を、仕様変更に合わせて 30 にしてください。変更箇所はここだけです」

## 要件チェックリスト
1. [critical] derive-optimal-solution の重い比較プロトコルを適用しない
2. [critical] 解空間が一意に固定されているため skip と判断する
3. 合意済み仕様を再オープンしない
4. 余計な代替案・採点表・帰結予測を作らない

## タスク
1. この入力で derive-optimal-solution を適用すべきか判定する
2. skip するなら、その境界判断を短く説明する
3. 実際のコード変更は行わない
4. 最後に下記レポートを返す

## レポート構造
- 成果物: apply / skip の判断と理由
- 要件達成: 各項目 ○/×/部分的（理由付き）
- 不明瞭点: SKILL.md で詰まった箇所
- 裁量補完: 指示で決まっておらず自分で補った箇所
- 再試行: 同じ判断をやり直した回数と理由

250 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |

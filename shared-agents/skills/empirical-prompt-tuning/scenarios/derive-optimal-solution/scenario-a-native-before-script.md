# derive-optimal-solution / シナリオ A（手段アンカー：script より native 設定）

## 対象

`~/.agents/skills/derive-optimal-solution/SKILL.md`

## ユーザー入力

「GitHub Linguist で generated 扱いにしたいファイルが増えたので、対象を列挙する `scripts/update-linguist-generated.mjs` を追加して CI で毎回実行する形にして。実装まで進めてよい」

## 要件チェックリスト

1. [critical] ユーザーが script 追加まで指定していても、その手段を所与にせず目的（generated 判定を一貫して管理する）へ戻る
2. [critical] repository / platform の native 設定（例: `.gitattributes` / Linguist 属性）や既存設定で解けないかを、script 実装より先に検証する
3. script / native 設定 / 現状維持または別の軽量案を比較し、同等効果なら責務の軽い案を優先する
4. 「実装まで進めてよい」を、指定手段への無条件合意とは解釈しない
5. 選んだ案と、script 案を採らない場合の理由を明示する

## subagent 投入プロンプト

```
あなたは ~/.agents/skills/derive-optimal-solution/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.agents/skills/derive-optimal-solution/SKILL.md を Read で読んでから実行してください。

## シナリオ
ユーザー入力: 「GitHub Linguist で generated 扱いにしたいファイルが増えたので、対象を列挙する scripts/update-linguist-generated.mjs を追加して CI で毎回実行する形にして。実装まで進めてよい」

## 要件チェックリスト
1. [critical] script 追加を所与にせず、目的へ戻る
2. [critical] native / 既存設定で解けないかを script より先に検証する
3. 複数案を比較し、同等効果なら責務の軽い案を優先する
4. 「実装まで進めてよい」を指定手段への無条件合意と解釈しない
5. 選択理由を明示する

## タスク
1. derive-optimal-solution に従って、実装前の解法選択まで実演する
2. 実際のコード変更は行わない
3. 最後に下記レポートを返す

## レポート構造
- 成果物: 問題の再構成、比較した案、推奨
- 要件達成: 各項目 ○/×/部分的（理由付き）
- 不明瞭点: SKILL.md で詰まった箇所
- 裁量補完: 指示で決まっておらず自分で補った箇所
- 再試行: 同じ判断をやり直した回数と理由

400 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |

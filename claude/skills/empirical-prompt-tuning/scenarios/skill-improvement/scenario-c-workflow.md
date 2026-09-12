# skill-improvement / scenario C（workflow redesign）

## 対象

`packages/core/skills/skill-improvement/SKILL.md`

## ユーザー入力

「既存 skill の references を整理して、agent の読み落としを減らしたい。本文を短くするだけで済むか、実測が必要か判断して」

## 要件チェックリスト

1. [critical] reference routing / progressive disclosure の変更として `writing-for-agents` を選ぶ
2. [critical] agent の読み落としが behavior に影響するため empirical 評価を gate にする
3. [critical] 本文・reference・scenario のどこを変更するかを分け、目的を拡張しない
4. 修正前に baseline と固定 checklist を作り、hold-out で過適合を確認する

## subagent 投入プロンプト

```
あなたは白紙の実行者です。packages/core/skills/skill-improvement/SKILL.md を読んで次の依頼への対応を実演してください。コード編集や git 操作はせず、改善方針と評価 plan まで返してください。

依頼: 既存 skill の references を整理して、agent の読み落としを減らしたい。本文を短くするだけで済むか、実測が必要か判断して。

要件: (1)writing-for-agentsの選択 (2)behavior影響に対するempirical gate (3)本文/reference/scenarioのscope分離 (4)baseline/checklist/hold-outを○/×/部分的で判定する。不明瞭点、裁量補完、再試行も返す。
```

## 最終実行結果

| 日付 | 判定 | 精度 | 備考 |
| --- | --- | --- | --- |
| 2026-08-31 | ○ | 100% | fresh subagent。writing-for-agents の選択、behavior に対する empirical gate、scope 分離、hold-out を確認。tool_uses / duration_ms は取得不可 |

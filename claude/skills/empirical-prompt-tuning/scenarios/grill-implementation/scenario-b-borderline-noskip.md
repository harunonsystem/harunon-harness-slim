# grill-implementation / シナリオ B（境界：スキップすべきでない軽微機能追加）

## 対象

`~/.claude/skills/grill-implementation/SKILL.md`

## ユーザー入力

「既存のユーザー一覧ページに年齢フィルタを追加したい」

## 要件チェックリスト

1. [critical] grill-implementation をスキップせずに実行する（複数の設計判断が必要なため）
2. [critical] 既存のフィルタ実装を Grep で調査する意図が示される
3. 年齢 UI（slider vs min/max 入力 vs 既定範囲ボタン）についての質問がある
4. API パラメータ形状（min/max vs range string）についての質問がある
5. 1 問 1 答で進む

## subagent 投入プロンプト

```
あなたは ~/.claude/skills/grill-implementation/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.claude/skills/grill-implementation/SKILL.md を Read で読んでから実行してください。

## シナリオ B（スキップすべきでない境界ケース）
ユーザー入力: 「既存のユーザー一覧ページに年齢フィルタを追加したい」

## 要件チェックリスト
1. [critical] grill-implementation をスキップせずに実行する（複数の設計判断が必要なため）
2. [critical] 既存のフィルタ実装を Grep で調査する意図が示される
3. 年齢 UI（slider vs min/max 入力 vs 既定範囲ボタン）についての質問がある
4. API パラメータ形状（min/max vs range string）についての質問がある
5. 1 問 1 答で進む

## タスク
1. grill-implementation スキルを読んで判断
2. 最初の 2-3 質問だけ実演（以降はユーザー回答次第なので省略可）
3. 最後に下記レポートを返す

## レポート構造
- 成果物: 判断結果と最初の質問群
- 要件達成: 各項目 ○/×/部分的
- 不明瞭点: grill-implementation SKILL.md で詰まった箇所
- 裁量補完: 自分の判断で埋めた箇所
- 再試行: 回数

300 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-04-24 | ○ | 80% | 全達成 | API 質問は Q1 回答待ち状態で予告扱いになった。実運用なら問題なし |

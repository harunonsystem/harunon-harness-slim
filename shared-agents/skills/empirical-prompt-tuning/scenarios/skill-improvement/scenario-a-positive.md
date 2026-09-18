# skill-improvement / scenario A（positive trigger）

## 対象

`packages/core/skills/skill-improvement/SKILL.md`

## ユーザー入力

「既存の migration skill の trigger と PR 分割の指示を改善したい。実際に agent が誤解しないかも確認して」

## 要件チェックリスト

1. [critical] `skill-improvement` を起動し、対象・scope・scenarios・gate を確定する
2. [critical] capability / 文書構造 / empirical の責務を分離して順序付ける
3. [critical] fresh baseline、one-theme patch、hold-out を含む
4. production code と commit / push / PR を改善評価の scope に含めない

## subagent 投入プロンプト

```
あなたは白紙の実行者です。packages/core/skills/skill-improvement/SKILL.md を読んで次の依頼への対応を実演してください。コード編集や git 操作はせず、改善 workflow の plan と report まで返してください。

依頼: 既存の migration skill の trigger と PR 分割の指示を改善したい。実際に agent が誤解しないかも確認して。

要件: (1)対象/scope/scenarios/gate (2)skill-creator、writing-for-agents、empirical-prompt-tuningの責務分離 (3)fresh baseline、one-theme patch、hold-out (4)production code/git操作をscope外、を○/×/部分的で判定する。不明瞭点、裁量補完、再試行も返す。
```

## 最終実行結果

| 日付 | 判定 | 精度 | 備考 |
| --- | --- | --- | --- |
| 2026-08-31 | ○ | 100% | fresh subagent。対象/scope/gate、3 sub-skill の分離、baseline→patch→hold-out、git scope 外を確認。nested dispatch の実行メタデータは取得不可 |

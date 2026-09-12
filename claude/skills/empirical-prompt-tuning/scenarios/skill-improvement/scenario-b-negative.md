# skill-improvement / scenario B（negative trigger）

## 対象

`packages/core/skills/skill-improvement/SKILL.md`

## ユーザー入力

「この skill を使って UserManagement の migration plan を作って」

## 要件チェックリスト

1. [critical] `skill-improvement` を起動せず、対象 migration skill の通常実行へ案内する
2. [critical] skill 自体の改善と、skill を使った production task を混同しない
3. migration の実行やコード編集を `skill-improvement` の責務に含めない

## subagent 投入プロンプト

```
あなたは白紙の実行者です。packages/core/skills/skill-improvement/SKILL.md を読んで次の依頼への対応を実演してください。今回は通常の task 実行であり、skill 自体の改善ではありません。

依頼: この skill を使って UserManagement の migration plan を作って。

要件: (1)skill-improvementを起動しない (2)改善とproduction taskを分離 (3) migration実行/コード編集をこのskillの責務にしない、を○/×/部分的で判定する。不明瞭点、裁量補完、再試行も返す。
```

## 最終実行結果

| 日付 | 判定 | 精度 | 備考 |
| --- | --- | --- | --- |
| 2026-08-31 | ○ | 100% | fresh subagent。通常 task と skill 改善の分離、skill-improvement の非発火を確認。tool_uses / duration_ms は取得不可 |

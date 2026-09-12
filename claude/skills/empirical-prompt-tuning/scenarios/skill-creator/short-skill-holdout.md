# skill-creator / 短いskill hold-out

## 対象

`packages/core/skills/skill-creator/SKILL.md`

## ユーザー入力

ユーザー依頼: 既存のClaude限定skill report-exportの構成案のみ。短いSKILL.mdは60行で、共通検証8行、TSV出力10行、JSON出力12行、残りはtriggerと完了条件。既存scripts/export.pyは両形式を出力できる。繰返す長文も大きい仕様表もない。name/description/license/disable-model-invocation:trueを維持。スクリプトとライセンスは変更不要。出力値と手動起動を変えずトークン効率を確認したい。
具体的な構成と検証方針を短く提案。ファイル変更、初期化、公開、配布、アーカイブ作成は不要。実checkoutは対象外。別agent禁止。

## 要件チェックリスト

1. [critical] 60行のskillを不要にreferenceへ分割しない
2. [critical] 既存のscript、license、disable-model-invocation、手動起動、出力値を維持する
3. [critical] 構成案だけを短く返し、変更やarchive作成をしない

## subagent 投入プロンプト

上のユーザー入力だけを読み、`skill-creator` に従って短い構成案を返す。checkoutや変更、別agent起動は行わない。

## 最終実行結果

2026-09-11 hold-out: 3 critical要件を達成。追加referenceなしの構成を提示。

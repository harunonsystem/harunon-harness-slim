# skill-creator / CSV-PDF構成案

## 対象

`packages/core/skills/skill-creator/SKILL.md`

## ユーザー入力

ユーザー依頼: 既存skillの構成案だけを作ってください。ファイル変更、初期化、配布・公開・アーカイブ作成はまだ不要です。
対象は自作skill invoice-tools。description「CSVの請求データの整形とPDF請求書出力」。SKILL本文には共通の入力検証の後、CSV列名の対応表150行、PDFテンプレート仕様180行、共通の金額チェックが記載されています。scripts/には既存convert_csv.pyとrender_pdf.pyがあり、書き直す必要はありません。
frontmatterはname/description/license/compatibilityと既存のdisable-model-invocation:trueです。このskillはClaude限定として配布しています。
要望: CSVだけ使う場合のcontextを軽くしたい。出力金額と既存の手動起動ポリシーは変えない。外部upstreamのtax-reference skillはrulesync管理なので編集しない。
skill-creatorに従って、具体的なファイル構成・読み込み条件・検証方針を返してください。評価のため別agentを起動する必要はありません。

## 要件チェックリスト

1. [critical] CSV/PDFの長文だけを条件付きreferenceへ分離する
2. [critical] 既存script、金額チェック、license、手動起動、upstream境界を維持する
3. [critical] 構成案だけを返し、初期化・配布・公開・archive作成をしない

## subagent 投入プロンプト

上のユーザー入力だけを読み、`skill-creator` に従って構成案を返す。checkoutや変更、別agent起動は行わない。

## 最終実行結果

2026-09-11 fresh評価: 3 critical要件を達成。CSV-only時にPDF referenceを読まない構成を提示。

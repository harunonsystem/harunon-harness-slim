---
description: PR本文をreviewer-firstに構成する規約。PR作成前に明示Readする。
paths:
  - "**/pr-body.md"
---

# PR Body Writing

PR本文は lab notebook ではなく reviewer 向けの briefing。diff を読む前に「なぜ」「変更の形」「証拠」「merge risk」が短時間で分かるようにする。

## 情報順序

repo固有 template がない場合は次の順序を使う。

1. `## Why`
   - 何が問題だったか / なぜ今変えるかを1〜3文。
   - 実装手段の説明から始めない。
2. `## Shape of change`
   - 変更内容そのものを必ず要約する。
   - 図が文章より速い場合は `show-me` の形式選択から最小の1図を使う。
   - 図が有効でない場合は、契約・挙動・責務がどう変わるかを1〜3項目の短い文章で書く。
3. `## Evidence`
   - 変更が効いた証拠を before → after で示す。
4. `## Merge risk`
   - `Door`: `two-way`（容易にrollback可能）か `one-way`（不可逆または復旧コストが高い）。
   - `Blast radius`: 影響対象を短く具体化する。
5. `## Notes`
   - non-goal、互換性、残件、review skip などがある場合だけ置く。
   - 空なら見出しごと省略する。

既存の `.github/PULL_REQUEST_TEMPLATE.md` がある場合は、その見出し・checklistを優先する。ただし各欄の中ではこの情報優先度を維持し、同じ内容を複数セクションに重複させない。

## Shape of change

`Shape of change` 自体は必須。図は装飾ではなく review navigation なので、差分の理解時間を縮める場合だけ使う。図が有効でない変更では、同じsectionに短い変更要約を書く。

非自明な構造・制御フロー・責務変更では `show-me` を使い、PR本文に貼れるMarkdown表現へ落とす。HTML artifact はPR本文には埋め込まない。

- **ロジック / policy**: 疑似コード
- **runtime control flow**: call tree
- **UI / component structure**: component tree または diff sketch
- **責務移動 / broad refactor**: shallow file tree
- **component interaction / data flow / sequence**: Mermaid
- **既存形状への局所変更**: `diff` sketch
- **visual UI change**: screenshot before / after を Evidence に置く

図には、reviewer が判断するために必要な call / state / boundary / ownership だけを残す。実ファイル一覧の転記や全アーキテクチャ図は作らない。

## Evidence

「テストを追加した」ではなく、何が失敗し、何が通るようになったかを書く。

- UI: screenshot before → after を優先。
- behavior / bug fix: failing repro → passing repro。
- testable logic: failing test → passing test。必要ならテスト手順を短い疑似コードで示す。
- performance: 主指標を `before → after` と単位付きで示す。
- test / lint / typecheck / build は、実際に実行したものと結果だけを書く。
- 未実行は成功したように書かず、理由を明記する。

## Merge risk

- `Door` は rollback / restore の実態で判定する。通常のcode-only変更は多くの場合 `two-way`。
- migration、destructive data change、external contract、security boundary、irreversible side effect は `one-way` の可能性を検討する。
- `Blast radius` は Low/Medium/High のラベルだけで終わらせず、影響対象を1文で書く。
- trivial docs / typo のように risk 情報がreview判断を変えない場合はこのsectionを省略してよい。

## 書き方

- Summary / Design / What changed のように同じ説明を二重化しない。
- commit log や変更ファイル一覧を本文へ転記しない。
- 「何を実装したか」より「何が変わるか」を優先する。
- reviewer がdiffを読む順序に意味がある大きめのPRだけ、短い `Review path` を追加してよい。
- issue / Linear task がある場合は Why の末尾かtemplate所定欄にリンクする。
- P3 / scope外 finding は Notes の「残件」に finding 単位で書く。
- reviewer が quota / credit 切れでskipされた場合は Notes に `Review: SKIP (quota)` と理由を1行で書く。
- 小さいPRは短くする。大きいPRでも本文をlab notebook化せず、詳細ログはartifactやリンクへ逃がす。

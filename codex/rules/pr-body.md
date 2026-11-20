---
description: PR本文をreviewer-firstに構成する規約。PR作成前に明示Readする。
paths:
  - "**/pr-body.md"
---

# PR Body Writing

PR本文は lab notebook ではなく reviewer 向けの briefing。diff を読む前に「変更理由」「やったことと変更範囲」「トレードオフ」「検証結果と確かめ方」「影響範囲（merge risk）」が短時間で分かるようにする。

## 情報順序

repo固有 template がない場合は次の順序を使う。

1. `## Why`
   - 何が問題だったか / なぜ今変えるかを1〜3文。
   - 実装手段の説明から始めない。
2. `## Shape of change`
   - やったことと変更範囲（カバーする範囲と、follow-up 等で意図的に対象外にした範囲）を要約する。
   - 図が文章より速い場合は `show-me` または `statechart` から最小の1図を使う。
   - 図が有効でない場合は、契約・挙動・責務がどう変わるかを1〜3項目の短い文章で書く。
3. `## Tradeoffs`
   - 検討したが採用しなかった案と理由。
   - reviewer が疑問に持ちそうな実質的な設計分岐があった場合のみ1〜3項目で書く。選択肢が自明な変更では見出しごと省略する。
4. `## Evidence`
   - 変更が効いた検証結果（before → after）と、reviewer が自分で再実行・確認できるやり方（コマンドや手順）を示す。
5. `## Merge risk`
   - `Door`: `two-way`（容易にrollback可能）か `one-way`（不可逆または復旧コストが高い）。
   - `Blast radius`: 変更の影響範囲と安全・注意の理由を短く具体化する。
6. `## Notes`
   - 互換性、残件、review skip などがある場合だけ置く。
   - 空なら見出しごと省略する。

既存の `.github/PULL_REQUEST_TEMPLATE.md` がある場合は、その見出し・checklistを優先する。ただし各欄の中ではこの情報優先度を維持し、同じ内容を複数セクションに重複させない。

## 最終推敲

日本語のPR本文は、構成と事実関係を確定した後、PR作成ツールへ本文を渡す直前に Agent Skill `slop-word-refactor` を明示的に適用し、domain は `business` を選ぶ。ここでの `slop-word-refactor` は shell command を実行する意味ではなく、harness が配布した skill を読み込んで本文を推敲する工程を指す。

`slop-word-refactor` は構成や事実を作る工程ではなく、確定済みの本文からAI特有の言い回し、不自然な比喩、過剰な装飾、冗長さを除く最終推敲として使う。要約や箇条書きのドラフト作成時は `slop-word-refactor` の手順（短くする前に口頭説明を組み立てる）で文脈と意味を保ち、その上で `slop-word-refactor` による最終推敲へ渡す。技術的制約、数値、Evidence、Merge risk、未実行項目、残件は削除・追加・断定変更しない。変換後にこれらが元のdraftと一致していることを確認してから、その出力を `gh pr create` または GitHub app の pull-request tool へ渡す。

PR本文が英語のみの場合はこの工程を省略してよい。`slop-word-refactor` が利用できないruntimeでは本文をそのまま公開せず、同じ原則で手動推敲してから作成する。

## Shape of change

`Shape of change` 自体は必須。何を変え、何を今回の変更範囲から意図的に外したか（Scope）を1〜3項目で明記する。図は装飾ではなく review navigation なので、差分の理解時間を縮める場合だけ使う。図が有効でない変更では、同じsectionに短い変更要約を書く。

非自明な構造・制御フロー・責務変更では `show-me` または `statechart` を使い、PR本文に貼れるMarkdown表現へ落とす。HTML artifact はPR本文には埋め込まない。

- **ロジック / policy**: 疑似コード
- **runtime control flow**: call tree
- **UI / component structure**: component tree または diff sketch
- **責務移動 / broad refactor**: shallow file tree
- **component interaction / data flow / sequence**: Mermaid
- **状態遷移 / プロトコル / 並行フロー**: Mermaid `stateDiagram-v2`（不変条件の形式検証を伴う場合は `statechart` の出力図）
- **既存形状への局所変更**: `diff` sketch
- **visual UI change**: screenshot before / after を Evidence に置く

図には、reviewer が判断するために必要な call / state / boundary / ownership だけを残す。実ファイル一覧の転記や全アーキテクチャ図は作らない。

## Tradeoffs

実質的な設計判断（`architect` / `derive-optimal-solution` で比較した代替案など、reviewer が「なぜ別案にしなかったのか」と疑問に持つ分岐）がある場合のみ、採用しなかった案と却下理由を1〜3項目で書く。

実質的な分岐がない変更では見出しごと省略し、欄を埋めるための架空の代替案を書かない。

## Evidence

「テストを追加した」ではなく、何が失敗し、何が通るようになったか（検証結果）と、**reviewer が手元で再実行して確かめられるコマンド・手順（確かめ方）**を併記する。

- UI: screenshot before → after を優先。
- behavior / bug fix: failing repro → passing repro。
- testable logic: failing test → passing test。必要ならテスト手順を短い疑似コードで示す。
- 状態マシン・形式検証（`statechart` 等）: 検証した不変条件（INVARIANT）、Mermaid statechart（バグ修正なら `breaks` の最短反例パス、新規・正常系なら状態遷移図）、モデルが省略した前提、および再生成コマンドを示す。状態遷移図で反例解消や遷移の正しさが即断できる場合は動画添付を不要とする。
- performance: 主指標を `before → after` と単位付きで示す。
- test / lint / typecheck / build は、実際に実行したものと結果・実行コマンドを書く。
- 未実行は成功したように書かず、理由を明記する。

## Merge risk

- `Door` は rollback / restore の実態で判定する。通常のcode-only変更は多くの場合 `two-way`。
- migration、destructive data change、external contract、security boundary、irreversible side effect は `one-way` の可能性を検討する。
- `Blast radius` は Low/Medium/High のラベルだけで終わらせず、影響対象を1文で書く。
- trivial docs / typo のように risk 情報がreview判断を変えない場合はこのsectionを省略してよい。

## 書き方

- Summary / Design / What changed のように同じ説明を二重化しない。
- commit log や変更ファイル一覧を本文へ転記しない。
- 箇条書き・要約は「説明してから短くする」（`slop-word-refactor`）: 要約や箇条書きを作成する際は、単に文字数を削るのではなく、まず「口頭で相手にどう説明するか」を考えて文脈・因果・条件を通した上で、意味を保って短く整える。言葉を削りすぎて文脈が抜けた短縮や、唐突な否定形（『〜を意味するわけではない』）から入る不自然な文章を避ける。
- 「何を実装したか」より「何が変わるか」を優先する。
- repo に `GLOSSARY.md` があれば、その用語で書く。
- コードベースが単語帳: クラス名・関数名・ファイル名・CLIフラグは日本語に意訳・言い換えせず、実際のシンボル名をそのままバッククォート（`...`）で書く。`slop-word-refactor` 推敲時もコード識別子は一切変えない。
- reviewer がdiffを読む順序に意味がある大きめのPRだけ、短い `Review path` を追加してよい。
- issue / Linear task がある場合は Why の末尾かtemplate所定欄にリンクする。
- P3 / scope外 finding は Notes の「残件」に finding 単位で書く。
- reviewer が quota / credit 切れでskipされた場合は Notes に `Review: SKIP (quota)` と理由を1行で書く。
- 小さいPRは短くする。大きいPRでも本文をlab notebook化せず、詳細ログはartifactやリンクへ逃がす。

## 本文の渡し方

本文を検査する hook はコマンド文字列を展開せずに読む。次の形でないと検査できず拒否される。

- `gh pr create` / `gh pr edit` は他のコマンドと `&&`・`;`・パイプで連結せず、単独で実行する。
- 本文ファイルは先に書き終えてから、`--body-file` に絶対パスをそのまま書く。`$VAR`・`$(...)` を含むパスは展開されない。
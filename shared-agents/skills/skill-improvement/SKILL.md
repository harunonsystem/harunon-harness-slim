---
name: skill-improvement
description: 既存 skill・agent 指示の trigger、手順、参照、出力を改善・評価する。対象 skill の実行や通常のコード修正には使わない。
---

# Skill improvement

既存の skill / agent 指示を改善する入口。対象の仕事や利用範囲は拡張しない。

## 保護規約の不変性（Immutability Guard）

改善の過程で、以下の「保護されたコア規約」を緩和・削除・迂回する変更を行ってはならない（`core-standards.md`「禁止事項」適用）:
- `rules/review-policy.md` の REJECT 基準（特に Old Code Failure やセキュリティ境界）
- `rules/core-standards.md` の品質・テスト・安全基準
- テスト authoring gate や Junk patterns 判定

自己評価やテストの通過率を上げるためにゲートを緩める変更（Loosening Drift）は REJECT 対象。改善は「指示の明確化」「見落とし防止」「偽陰性の低減」「具体的な失敗例の追加」に限定する。

## 改善手順

1. 対象本文と参照先を読み、`target`・変更する `scope`・固定 `scenarios`・合否の `gate` を確定する。description と本文の不一致を記録する。本文・reference・scenario の変更は区別する。
2. 変更に必要な設計ガイドだけ読む。
   - capability / trigger / workflow の設計は `skill-creator`。
   - 文書構造・参照先・wording は `writing-for-agents`。未導入の環境では同じ観点を自分で確認する。
3. agent の判断・出力・読み落としに影響する変更は [empirical-prompt-tuning](../empirical-prompt-tuning/SKILL.md) の評価手順に従う。チェックリストを修正前に固定し、fresh baseline → one-theme patch → fresh 再実行 → hold-out で確認する。既存の評価シナリオは同 skill の `scenarios/` を探す。private 対象のシナリオは同じ private package に置く。
4. 変更と評価結果、未検証事項を報告する。綴り・リンク修正など判断を変えない変更は構造確認で足りる。実行評価を省いた場合は実測済みとしない。

評価の判定・停止条件・報告形式は `empirical-prompt-tuning` が正本。この入口に複製しない。
production code の変更・commit・push・PR・配布はこの skill の責務外。別途依頼された作業として扱う。

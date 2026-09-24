---
name: skill-improvement
description: 既存 skill・agent 指示の trigger、手順、参照、出力を改善・評価する。対象 skill の実行や通常のコード修正には使わない。
---

# Skill improvement

既存の skill / agent 指示を改善する入口。対象の仕事や利用範囲は拡張しない。

1. 対象本文と参照先を読み、`target`・変更する `scope`・固定 `scenarios`・合否の `gate` を確定する。description と本文の不一致を記録する。本文・reference・scenario の変更は区別する。
2. 変更に必要な設計ガイドだけ読む。
   - capability / trigger / workflow の設計は `skill-creator`。
   - 文書構造・参照先・wording は `writing-for-agents`。
3. agent の判断・出力・読み落としに影響する変更は [empirical-prompt-tuning](../empirical-prompt-tuning/SKILL.md) の評価手順に従う。チェックリストを修正前に固定し、fresh baseline → one-theme patch → fresh 再実行 → hold-out で確認する。既存の評価シナリオは同 skill の `scenarios/` を探す。private 対象のシナリオは同じ private package に置く。
4. 変更と評価結果、未検証事項を報告する。綴り・リンク修正など判断を変えない変更は構造確認で足りる。実行評価を省いた場合は実測済みとしない。

評価の判定・停止条件・報告形式は `empirical-prompt-tuning` が正本。この入口に複製しない。
production code の変更・commit・push・PR・配布はこの skill の責務外。別途依頼された作業として扱う。

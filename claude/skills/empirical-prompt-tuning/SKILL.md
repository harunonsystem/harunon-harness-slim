---
name: empirical-prompt-tuning
description: agent 向けテキスト指示（skill / slash command / task プロンプト / CLAUDE.md 節 / コード生成プロンプト）を、対象の目的を変えずに、白紙の実行者・固定シナリオ・hold-out で評価し、最小修正を反復する skill 改善オーケストレータ。プロンプトや skill を新規作成・大幅改訂した直後、またはエージェントの挙動不良の原因を指示側の曖昧さに求めたいときに使う。
---

# Empirical Prompt Tuning

プロンプトの品質は書いた本人には分からない。書き手が「明瞭だ」と思うものほど、別エージェントが読むと詰まる。**バイアスを排した実行者に実際に動かしてもらい、両面で評価して反復する** のが本 skill の核。評価予算を先に固定し、要件と hold-out を満たしたら止める。

## 単一オーケストレーション契約

呼び出し時は次を最初に確定する。
- `target`: 改訂対象の `SKILL.md` または指示ファイル。
- `scenarios`: 対象に同梱された `scenarios/`、または呼び出し側が指定した保存済みシナリオ。
- `scope`: trigger / workflow / reference routing / output contract / wording のどこを改善するか。
- `gate`: 固定チェックリストの `[critical]` 全達成、質的な不明瞭点、hold-out の過適合。

実行順は `inspect → baseline → fresh dispatch → diagnose → one-theme patch → fresh re-run → hold-out → report` に固定する。

## いつ使うか
- skill / slash command / タスクプロンプトを新規作成・大幅改訂した直後
- エージェントが期待通り動かず、原因を指示側の曖昧さに求めたいとき
- 重要度の高い指示（頻繁に使う skill、自動化の中核プロンプト）を堅牢化したいとき

## 評価入力の分離と予算
- 実行者には対象指示・生のタスク・必要な fixture だけを渡し、期待回答や合否チェックリストは採点側に保持する。
- 既定予算は baseline・修正後・hold-out 各 1 回の計 3 回。子からの再委譲は既定で禁止。

## ワークフロー

0. **Iteration 0 — description と body の整合チェック**（静的）: frontmatter `description` と本文のカバー範囲の乖離を検出・解消。
1. **ベースライン準備**: 評価シナリオ（2〜3種）と要件チェックリスト（3〜7項目、`[critical]` 必須）を固定。
2. **バイアス排除読み**: 白紙の実行者として新規 subagent を dispatch。自己再読は禁止。
3. **実行**: [subagent-contract](references/subagent-contract.md) に従ったプロンプトを渡し、成果物と自己申告レポートを回収。
4. **両面評価**: 質的（不明瞭点・裁量補完）と量的（成功/失敗、精度、steps、duration）を記録。評価軸と解釈基準は [evaluation-metrics](references/evaluation-metrics.md) を参照。
5. **差分適用**: 不明瞭点を潰す最小修正（1イテレーション1テーマ）。修正前に満たす判定項目を明示。
6. **再評価**: 新規 subagent で fresh 再実行。
7. **停止判定**: 修正後と fresh hold-out で全 critical 要件を満たし、未解決の不明瞭点が無ければ停止。

## 環境制約
新規 subagent を dispatch できない環境では本 skill は適用しない（自己再読による代替は禁止）。
記述の整合性・明瞭性だけをチェックしたい場合は「構造審査モード」として静的レビューのみを行う。

## 提示フォーマット & Red flags
提示用 Markdown 形式、および陥りがちな合理化（Red flags）は [subagent-contract](references/subagent-contract.md) を参照。

## 保存済みシナリオ
`scenarios/` 配下に対象 skill ごとの評価シナリオを保存している。改訂時は `scenarios/README.md` を参照。

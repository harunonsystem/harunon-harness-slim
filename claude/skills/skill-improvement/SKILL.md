---
name: skill-improvement
description: 既存の skill / slash command / agent 向け指示を、目的と利用範囲を維持したまま設計・文言・実挙動の順に改善するオーケストレータ。skill を編集した後、skill の trigger・workflow・reference routing・output contract を改善したいとき、または改善評価を忘れずに回したいときに使う。単に skill を使う依頼や通常のコード改善には使わない。
---

# Skill Improvement

既存 skill の改善を一つの入口で進める。対象 skill の仕事を実行するのではなく、対象 skill 自体を調査・設計・測定・改訂する。

## 責務の分離

- `skill-creator`: capability、workflow、trigger、resource の設計判断
- `writing-for-agents`: agent が読む文書の構造、pointer、progressive disclosure、冗長さの改善
- `empirical-prompt-tuning`: fresh subagent、固定シナリオ、hold-out による実挙動の測定
- この skill: 上記を対象と変更種別に応じて順序付け、改善を収束させる

codemod、formatter、単なる自己再読は改善プロセスそのものではない。対象 skill の目的・ドメインを増やす変更は、別の設計判断として扱う。

## 起動時に確定する入力

1. `target`: 改訂対象の `SKILL.md` または agent 指示ファイル
2. `scope`: `trigger`、`workflow`、`reference routing`、`output contract`、`wording` のどれか
3. `scenarios`: target に同梱された `scenarios/`。なければ実運用の中央値 1 本と edge 1〜2 本を変更前に固定する
4. `gate`: `[critical]` 要件、許容する質的曖昧さ、hold-out の合格基準

private / Extras の target は、その package の scenario を使う。core に複製して別の正本を作らない。

## オーケストレーション

### 1. Inspect

target の frontmatter、本文、参照先、近い既存 skill、利用可能な scenario を読む。description の主張と body の実装範囲を照合し、対象変更を production code の変更から分離する。

### 2. Select

- capability / workflow / resource / trigger の変更 → `skill-creator` の設計基準を適用
- pointer / 構造 / wording の変更 → `writing-for-agents` と必要な mechanics を適用
- agent の判断・出力・手順の正しさを変える変更 → `empirical-prompt-tuning` を必須にする
- 迷う場合は設計 → 文書構造 → empirical の順で全て通す

### 3. Baseline

Iteration 0 の description/body 整合を記録し、シナリオとチェックリストを変更前に凍結する。チェックリストには `[critical]` を最低 1 つ置く。評価者には対象本文と scenario だけを渡し、今回の修正意図や前回結果を渡さない。

### 4. Run and diagnose

各 scenario を新規 subagent で実行する。自己申告（不明瞭点・裁量補完・再試行）と、指示側の判定（critical、精度、取得可能なら tool 数 / duration）を分けて記録する。失敗は「どの要件文言が落ちたか」まで特定する。

### 5. Patch one theme

失敗や曖昧さに効く最小の変更を、1 iteration 1 theme で target またはその reference に適用する。変更前に「どの checklist item を満たす変更か」を明示する。シナリオを易しくして合格させない。

### 6. Re-run and hold-out

前回とは別の fresh subagent で baseline を再実行する。critical が全て達成され、質的な不明瞭点が減ったことを確認した後、未使用の hold-out を実行する。hold-out で直近平均から 15 points 以上落ちたら過適合として停止し、target の構造を見直す。

### 7. Report and hand off

次を一つのレポートにまとめる。

- 対象、scope、適用した sub-skill と references
- iteration ごとの scenario 判定、精度、critical 未達
- 不明瞭点、裁量補完、修正と checklist の対応
- hold-out 結果、未取得メタデータ、未解決事項
- production code と git state に加えなかったこと

改善評価の完了は skill の改訂完了であり、commit / push / PR / production migration の完了ではない。それらは通常の workflow で別途扱う。

## 停止条件

- scenario が固定できない → 設計を進めず、scenario を先に作る
- fresh subagent を dispatch できない → empirical は未実施と明記し、自己再読で代替しない
- 3 iteration 以上、新しい曖昧さが減らない → 差分修正を止めて構造を再設計する
- tool 数 / duration が取得できない → `取得不可` と記録し、数値だけの収束判定をしない
- 対象 skill の目的や production code を変える必要が出た → この workflow の scope 外として分離する

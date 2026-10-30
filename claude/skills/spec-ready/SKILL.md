---
name: spec-ready
description: 大きいIssueをコードベース・契約・既存方針にgroundしてSpec Ready化し、architecture/release境界を決め、実装可能な子Issueへ自動分割する。コード実装や単なるIssue分割には使わない。
user-invocable: true
---

# Spec Ready

`slop-word-refactor` は利用可能な場合だけ使用する。未導入の場合は、各手順の制約を保ち、その場で表現だけを推敲する。

PdM / product-level の大きい Issue を、実装 agent が迷わず着手できる状態まで具体化し、必要なら複数の子 Issue に分割する入口。
通常の粒度確認や分割承認のために人間を挟まない。Issue・repo・ADR・既存契約から決められない product decision だけを例外として止める。
コード実装、PR 作成、merge、feature flag の rollout 実行までは含まない。

## 完了条件

READY にできるのは、以下がすべて満たされた実装 slice だけ。親 Issue は全 slice が READY なら READY、それ以外は BLOCKED とする。親に未解決の slice があっても、依存しない slice の READY 判断と作成まで止めない。

- 目的、観測可能な outcome、受け入れ条件、out of scope が明確
- 既存 behavior との互換性を判定済み
- contract / migration / release boundary の方針が決まっている
- 状態を持つ機能（非同期・ライフサイクル・決済・認証等）は、状態検証ゲートを通過し、状態遷移・ガード条件・不変条件（Invariants）が子 Issue の受け入れ条件に反映されている
- 各子 Issue が fresh context の agent 1 セッションで扱える大きさかつ main に単独 merge 可能
- 依存関係、verification、cleanup 条件が明示されている

BLOCKED で人間の product decision を求める場合だけ、判断材料・選択肢・質問を確定した後に `slop-word-refactor --domain business` を最終推敲として適用する。READY のまま子 Issue を自動作成して次の agent workflow へ流す場合は適用しない。

## Workflow

### 1. Grounding
対象 Issue の本文・コメントと、関連コード・既存 contract・DB schema・feature flag・ADR・既存 PR を読む。
推測で仕様を決めず、既存の実態を先に確認する。解法が複数残る場合の比較は `derive-optimal-solution` に従う。

### 2. Spec synthesis & 状態検証ゲート
親 Issue は product outcome の単位として維持する。
最低限、Problem / outcome、Acceptance criteria、Out of scope、維持すべき既存 behavior、unresolved decisions を確定する。

**状態検証ゲート**:
対象が「非同期ジョブ」「決済・認証フロー」「複数ステップのUI」「分散・イベント同期」など**状態（State）を持つ場合、このステップを省略してはならない**。
1. **モデル化**: 主要な状態（States）、イベント（Events）、不変条件（Invariants: 二重実行禁止など）を特定する。
2. **検証（`/statechart` の実行）**: `/statechart` を呼び出してモデル化と検査を行い、デッドロック、未処理イベント（タイムアウト、キャンセル、ネットワーク切断、重複受信）、不変条件違反がないかを検証する。
3. **成果物の反映**: 検出された考慮漏れ（反例シナリオ）を仕様に盛り込み、生成された状態遷移表または Mermaid ステート図を、該当する子 Issue の「受け入れ条件（Acceptance criteria）」に必ず含める。

### 3. Architecture classification & Release boundary
behavior の互換性（`compatible` / `parallel-v2`）と migration（`none` / `expand-migrate-contract`）、および release boundary を判定する。
詳細な設計パターン（v2境界、Expand-Migrate-Contract、flag seam等）は [architecture-patterns](references/architecture-patterns.md) を参照。

### 4. 子Issue分割と公開
親 Issue を 1 PR にまとめず、1振る舞い単位の vertical slice に分割して configured issue tracker に公開する。
分割原則、子Issue要件、および Idempotent な公開ルールは [decomposition-rules](references/decomposition-rules.md) を参照。

## BLOCKED 条件

以下の判断だけは人間へ上げる。親 Issue へのコメントに調査済みの事実、未決事項、選択肢を記録する。
- A/B どちらの product behavior が正しいか資料から決まらない
- backward compatibility を捨ててよいか product / external contract 上決まらない
- rollout 対象・権限・課金など、コードから推論できない business rule が必要
- tracker / project / repo が複数候補で既存規約から解決できない

「Issue が大きい」「分割案が複数ある」「vertical slice の粒度に迷う」だけでは止めない。最も main-safe で独立性の高い分割を選ぶ。

## 出力

最後に次だけを短く報告する。

```markdown
## Spec Ready
Status: READY | BLOCKED

Parent: ...
Slices:
- ISSUE-123: READY — compatible / none / <release boundary>
- <slice 名>: pending — parallel-v2 / expand-migrate-contract / <release boundary 方針> — <依存・未確定の契約>

Product decision needed: ... # 必要な場合のみ
Next action: ... # BLOCKED の場合のみ
```

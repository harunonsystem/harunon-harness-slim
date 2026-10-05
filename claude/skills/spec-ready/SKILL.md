---
name: spec-ready
description: 大きいIssueをコードベース・契約・既存方針にgroundしてSpec Ready化し、architecture/release境界を決め、実装可能な子Issueへ自動分割する。コード実装や単なるIssue分割には使わない。
user-invocable: true
---

# Spec Ready

`yomiyasu` は利用可能な場合だけ使用する。未導入の場合は、各手順の制約を保ち、その場で表現だけを推敲する。

PdM / product-level の大きい Issue を、実装 agent が迷わず着手できる状態まで具体化し、必要なら複数の子 Issue に分割する入口。

通常の粒度確認や分割承認のために人間を挟まない。Issue・repo・ADR・既存契約から決められない product decision だけを例外として止める。

この skill の起動は、対象 Issue の spec 整理と、必要な子 Issue の作成・関連付けまでを依頼されたものとして扱う。コード実装、PR 作成、merge、feature flag の rollout 実行までは含まない。

## 完了条件

READY にできるのは、以下がすべて満たされたときだけ。

- 目的、観測可能な outcome、受け入れ条件、out of scope が明確
- 既存 behavior との互換性を判定済み
- contract / migration / release boundary の方針が決まっている
- 各子 Issue が fresh context の agent 1 セッションで扱える大きさ
- 各子 Issue を main に merge しても、その時点の production を壊さない
- 依存関係と verification が明示されている
- rollout 後に消す旧経路・flag・compatibility code がある場合、その cleanup 条件がある

repo や既存資料から解けない product decision が残る場合は BLOCKED にし、必要な判断だけを列挙する。routine な「この分割でいいですか」は聞かない。

BLOCKED で人間の product decision を求める場合だけ、判断材料・選択肢・質問を確定した後に `yomiyasu --domain business` を最終推敲として適用する。選択肢の数、制約、既知/未知の境界、推奨の強さは変えず、推敲済み本文だけを返す。READY のまま子 Issue を自動作成して次の agent workflow へ流す場合は適用しない。

## Workflow

### 1. Grounding

対象 Issue の本文・コメントと、関係する実物を読む。

必要な範囲で確認するもの:

- 関連コードと既存の同種実装
- OpenAPI / GraphQL / protobuf 等の contract
- DB schema / migration
- feature flag と rollout の既存パターン
- ADR / GLOSSARY / product docs
- 関連 Issue / PR / test

推測で「v2 が必要」「flag が必要」と決めない。既存の seam、互換性制約、deploy/release の実態を先に確認する。新しい自作基盤が案にあるときだけ、既存設定・公式連携で足りるかと、残る不足要件を確認する。解法が複数残る場合の比較・必要性の検証は `derive-optimal-solution` に従い、同じ調査や様式を複製しない。

### 2. Spec synthesis

親 Issue は product outcome の単位として維持する。実装レイヤーの羅列に書き換えない。

最低限、次を確定する。

- Problem / outcome
- Acceptance criteria
- Out of scope
- 既存 behavior のうち維持すべきもの
- unresolved decisions

既存資料から一意に決まる内容はそのまま採用する。実質的に異なる解法が複数残る場合だけ `derive-optimal-solution` を使う。

### 3. Architecture classification

behavior の互換性と data / contract migration を別軸で判定する。behavior は `compatible` / `parallel-v2`、migration は `none` / `expand-migrate-contract` を基本とする。

#### Compatible change

既存 contract / behavior を壊さず追加できる。既存 path を拡張してよい。

#### Parallel behavior change

既存 behavior を残したまま新 behavior を安全に並存させる必要がある。

この場合は、既存 path に条件分岐を散らすより、切替可能な境界を作る。

- OpenAPI contract の意味が変わるなら、既存 schema/type に optional field を継ぎ足して曖昧にせず、必要に応じて明示的な v2 contract を作る
- generated type / client / API / UI は、旧 behavior と新 behavior の契約が異なるなら混ぜない
- flag の評価は page / container / service / repository / gateway 等、最も高く安定した seam で原則 1 回だけ行う
- leaf component や domain logic に feature flag 判定を散らさない
- repo が PostHog 等の flag provider を既に使っている場合はそれを使う。新しい provider を勝手に導入しない

例:

```text
Container / Service boundary
  ├─ V1 path
  └─ V2 path
       ↑
  existing feature flag
```

#### Data / contract migration

DB や共有データを変える場合、feature flag だけで安全性を作ろうとしない。

原則は Expand → Migrate → Contract。

- 先に backward-compatible な schema / contract を追加
- old/new consumer が並存できる期間を作る
- migration / backfill を行う
- new path の rollout 完了を確認してから old contract を削除

destructive migration、auth / permission / billing 等、repo の既存 policy 上 high-risk な変更は、その policy の gate を保持する。

### 4. Release boundary

コードが main / production に存在することと、ユーザーへ exposure することを分けられるか確認する。

user-visible behavior change で既存の feature flag 基盤がある場合は、release boundary を明示する。

```yaml
release:
  exposure_controlled: true
  boundary: "<page | container | service | repository | gateway>"
  flag: "<existing/new flag key or TBD>"
  rollout: "<repo の既存 rollout policy>"
  cleanup_when: "<100% rollout + 安定確認など>"
```

内部 refactor、test-only、runtime behavior に影響しない docs など、exposure control が不要な変更に flag を強制しない。

### 5. Decompose into implementation issues

親 Issue をそのまま 1 PR にしない。必要な場合は子 Issue に分割する。

原則:

- 1 Issue = 1 本の振る舞いにする。複数 repo にまたがるなら、同じ Issue のまま repo ごとに PR を出す（`rules/issue-tracker.md`）
- fresh context の agent が単独で理解・実装・検証できる
- main に単独 merge 可能
- tracer-bullet の vertical slice を優先する
- schema / backend / frontend の水平分割だけで終わらせない
- 後続を明確に簡単にする prefactor / additive migration / shared contract は、独立して検証可能なら先行 Issue にしてよい
- stacked PR が必要なら依存を明示し、各段階の main-safety を保つ
- rollout / cleanup が実装と独立するなら別 Issue にする

各子 Issue に最低限含めるもの:

- What to build: 完成後に観測できる behavior
- Acceptance criteria
- Blocked by
- Verification
- Release / flag boundary（該当する場合）
- Cleanup obligation（該当する場合）

### 6. Publish without routine approval

分割案が上の条件を満たし、未解決の product decision がなければ、通常の粒度確認を挟まず configured issue tracker に子 Issue を作成する。

公開は idempotent に行う。作成前に親 Issue に既に関連付けられた子 Issue と依存関係を取得し、各 slice の outcome / acceptance criteria / parent relation を照合する。

- 同じ slice が既に存在するなら再利用し、必要な spec / relation だけ更新する
- 新規 slice だけを依存順に作成する
- 途中で tracker 更新に失敗した場合は、それまでに作成・更新した Issue ID を親 Issue へのコメントに記録して終了する
- 再実行時はその記録と tracker の現状から再開し、作成済み slice を再作成しない

tracker への書き込みは `rules/issue-tracker.md` に従う。作れるのは sub-issue・blocked by リンク・コメントだけで、ラベル・状態・親 Issue の本文は変えない。

親 Issue へのコメントに以下を残す。

- 確定した spec の要点
- architecture classification
- release boundary
- 作成・再利用した子 Issue と依存関係
- 部分的な publish で止まった場合は、完了済み Issue ID と未作成 slice

## BLOCKED 条件

以下だけは人間へ上げる。BLOCKED にする前に、親 Issue へのコメントに調査済みの事実、未決の product decision、判断に必要な選択肢、作成済み子 Issue があればその ID を記録する。後続セッションはその記録から再開する。

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

Behavior strategy: compatible | parallel-v2
Migration strategy: none | expand-migrate-contract
Release boundary: ...
Parent: ...
Children:
- ISSUE-123 ...
- ISSUE-124 ...

Product decision needed:
- ... # BLOCKED の場合のみ
```

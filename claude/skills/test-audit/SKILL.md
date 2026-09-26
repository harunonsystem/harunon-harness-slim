---
name: test-audit
description: テストの追加・変更・レビュー時に使う価値監査。低価値・実装結合・重複テストと、テスト専用の production seam を防ぐ。
---

# Test Audit

テスト数やカバレッジではなく、観測可能な振る舞い・独立した契約・実在する回帰を守る証拠として価値があるかを判定する。

## Authoring gate

テストを追加・実質変更する前に、次を答える。答えが出ない場合はテストを追加しない。

1. 何の observable behavior / invariant / independent contract を守るか。
2. どんな credible regression でこのテストが失敗するか。
3. 既存 coverage がなぜその回帰を捕まえないか。同じ contract は strongest practical owner boundary の primary test 1つを基本とし、別 layer に置くなら transport / lifecycle / integration など固有リスクを示す。
4. テストのためだけの export / flag / wrapper / injection hook / global を production code に要求していないか。要求するなら、実際の owner boundary で検証できないか先に見直す。

behavior-preserving refactor で壊れるテストは implementation を検証している疑いが強い。公開契約として必要な場合を除き、owner boundary の振る舞いへ移す。

バグ regression test は、修正前コードで意図した理由により失敗し、修正後に通ることを確認する。同じ bug scenario を通過する全 layer で繰り返さない。

## Junk patterns

次に該当するテストは、独立した契約を守る根拠がない限り追加しない。既存テストの監査では削除・統合候補にする。

- assertion のない coverage probe
- self-comparison / identity の再確認
- source / import / export list / manifest の単純な写経
- private predicate や call shape を、実際の boundary coverage と重複して検証するもの
- 同じ contract の重複 invocation
- shared helper の挙動を provider / caller ごとに同じ形で再演するもの
- test-only export / global / wrapper を維持するためだけのテスト
- production caller がなく tests だけが使う code path
- expected value を被テスト helper / renderer 自身から生成するもの
- mock が asserted behavior 自体を実装しているもの
- fixture が、本来 production owner が生成すべき receipt / ordering / persistence を先に与えてしまうもの
- capability flag や config declaration を読むだけで、約束された delivery / acknowledgement を実行しないもの
- 本来の path と無関係な guard / rejection で green になる negative control

## Retention bar

次を独立して守るテストは残す。

- public API / SDK / protocol / config / migration / storage / security contract
- platform / default / package / release / architecture contract
- observable な call ordering
- credible regression
- source inspection 自体が最小かつ独立した guard である場合

static / slow / source-based という理由だけで削除しない。implementation に見えても、それ自体が契約なら残す。

## Audit workflow

既存テストを削除・統合するときは、編集前に次を確認する。

- exact test name / location
- 実際に検出できる failure
- 対象 production seam の non-test caller
- 残る strongest owner-boundary proof
- test / seam が存在する理由と relevant history
- 削除で不要になる production / test-support code
- risk と focused validation

不明な候補を deletion count のために消さない。テスト削除で不要になる test-only production seam や dead path は、互換 alias として残さず同じ coherent change で削除する。

## Validation

- 変更した contract の owner test と隣接 test を最小範囲で実行する。
- bug regression は pre-fix failure の provenance と post-fix pass を示す。
- removed source assertion の代わりに実行可能な contract があるなら、その実コマンド / dry-run を確認する。
- production / tooling と tests / test-support の LOC を分けて報告する。
- coverage の維持自体を成功条件にしない。守る契約と failure detection が維持されていることを確認する。

## 出力

必要な項目だけ簡潔に報告する。

- 追加・保持した contract と owner boundary
- 削除・統合した low-value pattern
- pre-fix / post-fix regression proof
- 残した false positive 候補と理由
- production / test-support simplification
- 実行した focused validation

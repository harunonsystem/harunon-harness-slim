---
description: OSS/外部リポジトリへのコントリビューション規約。commit英語、本家スタイル遵守。
paths:
  - "**/oss-contribution.md"
---

## OSS コントリビューション規約

### 基本ルール
- commit messageは英語で書く
- 本家のコードスタイルに合わせる（自分のスタイルを持ち込まない）
- CodeRabbit等の自動レビュー提案は、既存スタイルと整合するか判断してから採用

### PRワークフロー
- fork → fork先でPR → 確認後に本家へPR
- GitHub UIの「Update branch」ボタンで済む操作をCLIで複雑にしない

### シンプルさの維持
- 既存のインラインスタイルが慣習なら従う
- 「シンプルに」と言われても機能的に必要なもの（propsスプレッド等）は消さない
- 極端から極端に振れない

### このリポジトリ（harunon-harness）を OSS 化・公開する場合の除外規約

`packages/core/skills/*/NOTICE.txt` に "do not redistribute" 等の再配布禁止が明記された vendored スキルは、公開前に必ず除外する（現時点: `efficient-fable`）。判定は `scripts/validate-harness.py` の `check_vendored_notices` が warning として一覧化する。README.md の「core は OSS 化しても問題ない構成」の文言もこの除外を前提にしている。

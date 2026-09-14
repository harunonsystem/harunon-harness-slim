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

### vendored スキルの再配布禁止

vendored スキルの `NOTICE.txt` に "do not redistribute" 等の再配布禁止が明記されている場合、外部公開・再配布の前に必ず除外する。harness では validator が対象を warning として一覧化する。

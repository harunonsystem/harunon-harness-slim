# ADR-002: core / extras の分離基準

## Status: Accepted

## Context

harness の skills, rules, hooks を「汎用（core）」と「プロジェクト固有（extras）」に分離する必要がある。core は OSS 化しても問題ない構成を維持する設計原則があり、会社名・プロジェクト固有パスの漏洩は設計違反。

過去に `design-review`（`docs/principal.md` 依存）、`figma-sync-tokens`（`src/designsystems/tokens/` 依存）、`self-review`（Rails/multi-tenant 固有）、`check-plan-model.sh`（`EXPECTED_ORG` に組織名をハードコード）が core に漏洩していた。

## Decision

以下のいずれかに該当するものは extras に配置する:

1. 会社名・org 名・社内サービス名が含まれる
2. 特定プロジェクトのディレクトリ構造・パスに依存する
3. 特定フレームワークの固有規約に強く依存する（汎用的な言及は可）

判断に迷ったら extras に置く（core 汚染を防ぐ）。

### Update 2026-09-11: 再配布不可の vendored は `packages/restricted/`

上記 3 基準は固有名・固有パス・固有規約のみを見ており、**ライセンス上 public に再配布できない
vendored** を捕まえられていなかった。実際に `efficient-fable`（upstream に LICENSE が無く
`NOTICE.txt` に再配布禁止と明記）が core に置かれ、「core は OSS 化しても問題ない構成を維持する」
という本 ADR の原則に反していた（public slim 配布の設計中に `validate-harness.py` の
`vendored-notices` check が検出）。

第 4 基準として「ライセンス上 public に再配布できない」を追加し、置き場は `packages/extras/` では
なく `packages/restricted/` とする。extras は private submodule なので未取得の環境
（`bootstrap.sh --core-only`）があり得るが、restricted は core と同じく常に配布される必要がある
（自分では使う skill であり、配布から落ちるのは劣化）。詳細は `packages/restricted/README.md`。

環境固有の値（org 名等）は環境変数で注入し、core のコードにハードコードしない。

## Consequences

- `settings.json` の permissions に extras 側スキル名を直接書けない（extras 側の settings patch として管理）
- 新規スキル追加時に `add-skill-to-repo` が分離判定を案内する
- `.githooks/pre-commit` の BLOCKED_TERMS で会社固有名の漏洩を機械的に検出

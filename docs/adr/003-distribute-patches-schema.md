# ADR-003: distribute + patches スキーマによるターゲット定義

## Status: Accepted (Amended 2026-09-03 — distributeEntry に hookLibClosure を追加。2026-07-26: patches は削除、distribute / skillsTransform のみ現行)

## Context

各ターゲット（Claude, Codex, OpenCode）への配布内容と変換ルールを宣言的に定義する必要がある。ターゲットごとに異なる点:

- 指示ファイル名（CLAUDE.md vs AGENTS.md）
- パス prefix（`~/.claude/` vs `~/.codex/` vs `~/.config/opencode/`）
- ツール名（Claude Code vs Codex vs OpenCode）
- 固有セクション（Startup Self-Check は Claude のみ、Language は Codex のみ）
- skills の frontmatter フィールド（Claude 専用フィールドの除去）
- rules/skills の配布方式（コピー vs config 参照）

## Decision

`packages/targets/<name>/config.json` に以下のスキーマで定義:

- `distribute`: 「何を」「どこから」配布するかの宣言。`applyPatches: true` で patches 適用対象を指定
- `patches`: 変換ルールの配列。`remove-section`, `replace`, `add-section`, `modify-section` の4種
- `skillsTransform`: skills コピー時の frontmatter 変換ルール
- `configManagedResources`: config ファイル側で参照管理されるリソース（OpenCode 固有）

## Consequences

- ターゲット追加時は config.json を1ファイル書くだけ
- patches の適用順序は配列順。順序依存の変換がある場合は注意
- `replace` は全出現箇所を置換するため、意図しない箇所の置換に注意（`~/.claude/` → `~/.codex/` は安全だが、短い文字列の置換は危険）
- 2026-06-11 追記: patches の適用は当初 LLM（sync-settings スキル）が散文指示で行っていたが、`scripts/apply-patches.py` で決定論化した。`--check` により生成期待値とターゲット実体のドリフト検出が可能
- 2026-06-12 追記: apply-patches.py / sync-codex-skills.py は scripts/distribute.py（harness_lib）に統合
- 2026-07-26 追記: **patches / applyPatches を実装・スキーマごと削除した。** AGENTS.md 生成が `expandIncludes`（fragment 展開）へ移行して以降、本番 config での patches 宣言はゼロのまま実装だけが残っていた（テストは「未使用であること」を assert していた）。本 ADR のうち現行有効なのは `distribute` / `skillsTransform` / `configManagedResources` の宣言スキーマのみ。テキスト変換が再び必要になった場合は text surgery（patches）ではなく include fragment で表現する
- 2026-09-03 追記: distributeEntry に `hookLibClosure`（boolean）を追加。`<hooks dir>/lib/` 宛てのディレクトリ source に付けると、resolver が親ディレクトリへファイル単位で配る hook 群の `$HOOK_DIR/lib/<name>.sh` 参照を辿り、推移閉包だけを配布物に含める。それまで pi / omp / opencode の config.json が lib の閉包を手で列挙しており、lib 追加（denial-log.sh, f4573b1）が config 3 つを触り、列挙漏れが opencode の全 Bash deny（2026-08-05）になっていた。宣言は「hook 実体 + `<hooks dir>/lib/` 1 行」に閉じ、閉包の計算は runtime 非依存なので target ごとの分岐は持たない

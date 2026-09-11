# harunon-harness — プロジェクト指示

このリポジトリは AI コーディングツール（Claude Code / Codex / OpenCode）設定の SSOT。ドメイン用語と全体像は `CONTEXT.md`、過去の決定は `docs/adr/` を参照する。

## 最重要原則: SSOT-first

**設定の編集は必ずこのリポジトリ側（`packages/core/` または `packages/extras/_active/`）で行う。`~/.claude/` 等のライブ側を直接編集しない。**

- ライブ側を直接編集すると、次の bootstrap / sync-settings --push で SSOT の内容に**無言で巻き戻される**（実例: 2026-06-11 の codex review モデル設定インシデント。backup は `~/.claude/backups/bootstrap-*/` に残る）
- 緊急でライブを直した場合は、即日このリポジトリへ還流して commit する
- 配布: `./scripts/bootstrap.sh`（全ターゲット + 外部 skill）。1 ターゲットだけなら `--targets <name>`。操作の入口は `/sync-settings`

## レイアウト

| パス | 内容 |
| --- | --- |
| `packages/core/` | 配布物の SSOT（CLAUDE.md, RTK.md, commands.md, skills/, rules/, hooks/, agents/, commands/, settings.json） |
| `packages/extras/_active/` | 会社・プロジェクト固有（private submodule）。固有名が出るものは必ずこちら |
| `packages/targets/*/config.json` | ターゲット別の配布宣言（変換は expandIncludes / transform）。bootstrap.sh は distribute.py の殻なので宣言が唯一の真実 |
| `scripts/` | bootstrap（distribute.py の殻。外部 skill は curated-skills.py、codex local config は codex-local-config.py に委譲）/ distribute / validate-harness（check 実体は `harness_lib/validators/`、実行順は `validators.CHECKS`）+ tests |
| `packages/public-slim/` | 公開 slim 配布の宣言（`manifest.json` の allowlist / 加工 / gate）と slim 用の静的ファイル（LICENSE・README・CI・pi-agent の install スクリプト）。生成は `scripts/build-public-slim.py`（ロジックは `harness_lib/public_slim.py`）。生成物は SSOT ではない |
| `.githooks/` | pre-commit（禁止語ガード）/ pre-push（submodule 同期・ドリフト警告）。`git config core.hooksPath .githooks` で有効化 |

## 編集時の注意

- `packages/core/CLAUDE.md` はここのプロジェクト指示ではなく**配布用 global メモリ**。混同しない
- `packages/core/CLAUDE.md` は **Claude 専用**。Codex / OpenCode / pi / omp の常駐指示は `packages/targets/<t>/AGENTS.md`（共有ブロックは `packages/core/fragments/agents-md/` を include）が別 SSOT なので、CLAUDE.md の増減は他ターゲットへ波及しない。逆に fragments の変更は全ターゲットに波及する
- `paths:` frontmatter を持たない `rules/*.md` は毎セッション注入される。SSOT から消すだけではライブ（`~/.claude/rules/` 等）に残り常駐コストを払い続けるので、退役させたら各 `targets/*/config.json` の `obsoleteFiles` に配布先相対パスを宣言する
- 常駐文書（CLAUDE.md + RTK.md + 非 gate な rules）の合計バイト予算、CONTEXT.md の管理規模カウント、commands.md ↔ skills/ の対応、`rules/<name>.md` 参照の実在は validator が機械検証する
- shell script は bash 3.2（macOS 標準）互換で書く。shellcheck -S warning が CI でブロッキング

## 検証コマンド（変更後は必ず実行）

```bash
"$(mise which python3)" scripts/run-tests.py                          # Python テスト（クラス単位並列。-k で絞る）
node --test "scripts/tests/node/*.test.ts"                           # Node テスト（bridge / hookRunner）
"$(mise which python3)" scripts/validate-harness.py                  # メタ整合
"$(mise which python3)" scripts/distribute.py codex --check          # AGENTS.md ドリフト
shellcheck -S warning packages/core/hooks/*.sh scripts/*.sh .githooks/pre-commit .githooks/pre-push
```

`run-tests.py` は Python テストしか回さない。hook-pipeline.json / hook-runner / 各 runtime の
adapter を触ったら Node テストも回す（この 2 つを揃えないと、ローカル green のまま CI の
validate だけが落ちる。2026-09-06 に発生）。

CI（.github/workflows/ci.yml）が push/PR ごとに同じチェックを実行する（extras submodule は取得しない前提）。

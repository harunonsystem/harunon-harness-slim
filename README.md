# harunon-harness-slim

複数の AI コーディングエージェント（Claude Code / Codex / OpenCode / pi / omp）の設定を 1 つの SSOT から宣言的に配布するハーネスの公開版です。
skills・rules・hooks・agents・slash commands と、それらを各ランタイムの設定ディレクトリへ写す `distribute.py`、危険コマンドを止める安全 hook を含みます。

このリポジトリは **生成物** です。SSOT は `harunon-harness`（private）で、`scripts/build-public-slim.py` が
`packages/public-slim/manifest.json` の allowlist に従って組み立てています。ここで直接編集した内容は次の生成で巻き戻ります。

## 入っているもの

- `packages/core/` — 汎用ハーネス本体（skills / rules / hooks / agents / commands / policy / workflows / CLAUDE.md / settings.json）
- `packages/targets/*/config.json` — ランタイム別の配布宣言（何をどこへ、どう変換して置くか）
- `packages/runtimes/` — ランタイム側 adapter（opencode plugin / codex plugin skeleton など）
- `scripts/` — 配布（`distribute.py` / `bootstrap.sh`）、メタ整合の検証（`validate-harness.py`）、テスト
- `schemas/` — target config の JSON Schema
- `docs/adr/` — 設計判断の記録
- `.githooks/` — codename リーク防止の pre-commit と検証ゲートの pre-push

## 入っていないもの

- 会社・プロジェクト固有の skills / rules（private submodule。`packages/targets/*/config.json` の該当 source は生成時に落としています）
- ライセンス上再配布できない vendored skill（`docs/adr/002-*.md` 参照）
- 個人の作業記録（`plans/`）と作業履歴（`lessons.json`）
- 個人好みのツール前提の常駐文書（rtk のチートシート、rtk / gwm 前提の CLAUDE.md 節）

外部 skill（`rulesync.jsonc` / `rulesync.lock` に宣言。tdd / diagnosing-bugs / opencli-* など）は vendored コピーを持たず、`bootstrap.sh` が `rulesync install --frozen` で upstream から取得して配ります。それぞれの upstream のライセンスに従ってください（`docs/adr/011-*.md`）。

## 前提ツール

- Python 3.11+（`tomllib` を使います）と `pip install -r requirements.txt`。`mise.toml` に pin があるので mise を使うならそのまま解決できます
- Node 22+（hook runner と runtime adapter のテスト）
- `jq`、`shellcheck`
- `bootstrap.sh` は Python を mise 経由で解決します。mise を使わない場合は Python 3.11+ で `scripts/distribute.py <target> --push` を target ごとに直接実行してください
- hook のうち 2 つは特定 CLI を前提にします。`rtk-rewrite.sh` は rtk が無ければ何もせず素通りします（任意）。`enforce-gwm-for-worktree.sh` は worktree 作成を gwm 経由に強制するので、使わない場合は rigor profile を `casual` にするか `packages/core/policy/hook-pipeline.json` の配線から外してください

## 使い方

```bash
git config core.hooksPath .githooks       # pre-commit / pre-push を有効化（任意）
cp .env.example .env                      # BLOCKED_TERMS を自分の禁止語に書き換える（任意）

"$(mise which python3)" scripts/distribute.py claude --check   # ~/.claude とのドリフト確認
"$(mise which python3)" scripts/distribute.py claude --push    # 配布（既存ファイルは backup してから上書き）
"$(mise which python3)" scripts/distribute.py pi --list        # 配布されるパス一覧
```

target 名は `packages/targets/` のディレクトリ名（`claude` / `codex` / `opencode` / `opencode-launcher` / `pi` / `omp` / `shared-agents`）です。
pi だけを使う場合は、payload だけを切り出した `harunon-pi-agent-slim` の方が軽く済みます。

## 検証

```bash
"$(mise which python3)" scripts/run-tests.py                 # Python テスト（クラス単位で並列）
node --test "scripts/tests/node/*.test.ts"                   # hook runner / bridge のテスト
"$(mise which python3)" scripts/validate-harness.py          # メタ整合（配布宣言・hook 配線・skill frontmatter など）
```

## 設計の要点

- 配布は SSOT からライブへの一方向です。ライブ側を直接編集すると次の配布で巻き戻ります（`docs/adr/` と `CONTEXT.md` に背景があります）
- 危険コマンドの判定は `packages/core/policy/danger-rules.json` が SSOT で、hook はこの表を読みます。runtime ごとにどの hook をどの順で流すかは `policy/hook-pipeline.json` が宣言します
- 新しい target を足すときは `packages/targets/<name>/config.json` を書くだけで、`distribute.py` と validator が拾います

## License

MIT（`LICENSE`）。vendored skill にはそれぞれの NOTICE が付いています。

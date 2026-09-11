# ADR-011: 外部 skill は upstream を正本にし、SSOT から vendored コピーを退役させる

## Status: Accepted

## Context

`rulesync`（`rulesync.jsonc` + `rulesync.lock`）で upstream から取得する外部 skill と、`packages/core/skills/` に vendored した harness 版が、同名で 16 件重複していた。

重複していた状態の実害:

- bootstrap の curated コピーが harness 配布より**前**にあり、同名 skill は必ず harness 版が最後に上書きして勝つ。upstream の更新が反映されない
- upstream にしか無いファイル（`agents/openai.yaml`、`opencli-adapter-author` の `references/` 16 件）は harness 管理ディレクトリ内に残留する。distribution ledger の管理外なので `--check` では検出できない
- upstream が大きく育っていた 3 件（`opencli-usage` +154 行 / `opencli-browser` +411 行 / `opencli-adapter-author` +234 行と references 16 ファイル）が古い vendored 版で止まっていた

`packages/targets/claude/config.json` の notes には、engineering skills を `packages/core/skills/` で管理する旧決定と、その理由（正本が 2 系統に割れる・harness の rules が `/diagnosing-bugs` 等を名指し参照する・plugin 宣言が settingsSync の経路を持たない）が記録されていた。本 ADR は前 2 つの理由に別の解を与えて旧決定を置き換える。

## Decision

外部から届く skill は **upstream を正本**とする。

1. curated と重複していた 16 件のうち 13 件を `packages/core/skills/` から退役させ、rulesync に所有権を渡す
2. 例外 3 件は harness 側に残す（upstream に無いものを harness が持っているため）
   - `difit`: harness だけが "Review-and-Comment Workflow" 節（差分レビュー結果を `--comment` で流し込む手順）を持つ
   - `grill-with-docs`: upstream は「Call the Skill tool twice」と Claude 固有のツール名を書いており、複数 runtime へ配る harness の runtime 中立契約に反する
   - `improve`: harness だけが `LICENSE.md` を持つ
3. curated コピーを harness 配布の**後**（Step 2.5）に移し、upstream が最後に勝つ順序にする
4. curated の取得を **fail-closed**（`rulesync install --frozen`）にする。旧決定の理由「rules が `/diagnosing-bugs` 等を名指し参照する」への解であり、取得失敗時に参照先不在のまま配布完了と報告することを防ぐ
5. コピー先は `~/.claude/skills` と `~/.agents/skills` の 2 つで足りる。codex / opencode / pi / omp は `~/.agents/skills` を直読し、Claude Code だけが自分の configDir 配下しか読まない（CONTEXT.md「ツール間の差異」）
6. validator は `rulesync.lock` を curated skill 名の宣言元として読み、`commands.md` の対応チェックと `/skill` 参照の実在チェックで既知名に含める。実体の `.rulesync/skills/.curated/` は gitignore 済みで CI には存在しないため、lockfile が唯一の宣言元になる

## Consequences

- 外部 skill の更新は `rulesync install` で入る。harness 側での再 vendoring は不要
- 退役した 13 件はライブから distribution ledger 経由で削除され、直後に Step 2.5 が upstream 版を置く。13 件はいずれも upstream が harness 版のスーパーセットだったため、`obsoleteFiles` 宣言は不要
- ネットワーク断・`gh auth` 切れ・`rulesync.lock` のズレでは bootstrap が止まる。fail-open だった頃と違い、外部 skill 不在のまま配布完了と報告することはない
- 例外 3 件は upstream と意図的に分岐したままなので、upstream 側の更新は自動では入らない。差分を還元するか override を維持するかは都度判断する

## Update 2026-08-30

curated skill は distribution ledger 外の第二の配布経路のままだったため、「所有権と drift の答えが 2 つある」状態だった（`--check` が curated の drift を検出できず、bootstrap.sh Step 2.5 が bash `rm -rf` + `cp -RfX` で ~/.claude/skills と ~/.agents/skills を直接書き換えていた）。

claude / shared-agents の `distribute["skills/"].source` 配列に `.rulesync/skills/.curated/`（`resolver.CURATED_SKILLS_SOURCE`）を第三の source として追加し、既存の「後勝ち」合成（core → extras → curated）にそのまま乗せた。これにより:

- curated skill は他の source と同じ manifest エントリになり、`--check` が drift を検出し、`--push --prune` が退役 skill を削除する（旧 Step 2.5 の bash rm -rf を置き換え）
- rulesync.lock 宣言と `.rulesync/skills/.curated/` の実体のズレは `resolver._validate_curated_completeness` が fail-closed で検出する（旧 `curated-skills.py --require-present` を plan 時点の検証に移した）
- `.rulesync/skills/.curated/` が丸ごと未取得（rulesync 未実行）の場合は uninitialized submodule と同じ扱いで skip（incomplete destination）にし、curated skill 抜きの manifest として続行する。個々の宣言 skill が欠けている場合とは区別する
- `rulesync install --frozen` は bootstrap.sh に残る（Step 1.75。Step 2 の distribute push より前に移動。fail-closed の意味は変わらない）
- `scripts/curated-skills.py`（bootstrap.sh 専用 CLI）は削除。`harness_lib.curated_skills` の `list_curated_skills` / `invalid_skill_names` は resolver と validator が直接 import する

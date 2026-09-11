---
name: sync-settings
description: "harness (packages/core/) と各ターゲット（Claude Code, Codex, OpenCode, pi, omp, shared-agents）間の設定同期。--check でドリフト検出、--push で配布、--pull で取り込み、--update で更新チェック。「sync-settings」「設定同期」「ドリフト確認」「harness 更新」などで起動。"
user-invocable: true
argument-hint: "[--check|--push|--pull|--update] [claude|codex|opencode|pi|omp|shared-agents|opencode-launcher|all]"
references:
  - ../../../scripts/bootstrap.sh
  - ../../../scripts/distribute.py
  - ../../../scripts/harness-doctor.sh
  - ../../../schemas/target-config.schema.json
  - ../../../docs/adr/003-distribute-patches-schema.md
  - ../../../docs/adr/008-distribution-ledger.md
  - ../../../docs/adr/011-external-skills-upstream-as-source.md
---

# sync-settings

harness（`packages/core/` + `packages/extras/_active/`）を SSOT として、各ランタイムの設定ディレクトリに配布・同期する。

**この skill はコピー処理を自前で実装しない。** 実体は `scripts/distribute.py`（1 ターゲット）と、その殻の `scripts/bootstrap.sh`（全ターゲット + 外部 skill）。skill の仕事はモード選択・結果の読み方・スクリプトが見ない層（rulesync curated / 未管理スキル）の補完。

## 定数

- **harness root**: `git rev-parse --show-toplevel` で動的に解決
- **SSOT**: `<harness-root>/packages/core/`（会社・プロジェクト固有は `packages/extras/_active/`）
- **ターゲット宣言**: `<harness-root>/packages/targets/<name>/config.json`

## ターゲット

target 省略時は `all`。

| target | 配布先 | 主な中身 |
| --- | --- | --- |
| `claude` | `~/.claude` | CLAUDE.md / RTK.md / commands.md / rules / skills / hooks / agents / commands / workflows / policy |
| `codex` | `~/.codex` | AGENTS.md / RTK.md / rules / agents / codex 固有 skill / 各種 config.toml |
| `opencode` | `~/.config/opencode` | AGENTS.md / rules / agents / plugins / runtime（claude-hooks bridge・policy） |
| `pi` | `~/.pi/agent` | AGENTS.md / rules / agents / hooks / claude-hooks / extensions / policy / workflows |
| `omp` | `~/.omp/agent` | AGENTS.md / rules / policy / workflows / extensions |
| `shared-agents` | `~/.agents` | core + extras の**全 skill** / policy / workflows。codex・opencode・pi・omp が共有で読む |
| `opencode-launcher` | `~/.local/bin` | opencode 起動ラッパ 1 本 |

core skill が codex / opencode / pi / omp に届く経路は **shared-agents（`~/.agents/skills`）**。各ランタイムの `configDir` に skills/ を直接配ってはいない（codex だけ例外で、codex 固有 skill を `packages/targets/codex/skills/` から追加配布する）。

## モード

| モード | 実体コマンド |
| --- | --- |
| **引数なし** | `./scripts/bootstrap.sh --check`（= `--check all`）。**モードを省略したら必ず check に落とす** |
| `--check [target]` | `./scripts/bootstrap.sh --check [--targets <t1,t2>]` |
| `--push [target]` | `./scripts/bootstrap.sh [--targets <t1,t2>]` |
| `--pull <target>` | `./scripts/bootstrap.sh --pull --targets <target>`（target 必須。理由は下記） |
| `--update` | `git fetch` → `./scripts/harness-doctor.sh` → 差分の方向を判定（下の「更新チェック」節） |

`bootstrap.sh` は**モードを省略すると push** になる。`/sync-settings` を素で呼ばれたときに素の `bootstrap.sh` を実行すると、確認のつもりで全ターゲットを上書きする。必ず `--check` を明示する。

`push` / `pull` は 1 ターゲットでも失敗した時点で `exit 1` して残りを実行しない（`scripts/bootstrap.sh:288-290`）。全ターゲットを回したつもりが途中で止まっていることがあるので、終了コードと最後に出たターゲット名を必ず確認する。continue するのは `check` だけ（drift は結果であってエラーではないため）。

### runtime 単体指定には shared-agents を足す

core skill は各ランタイムの configDir ではなく **shared-agents（`~/.agents/skills`）** 経由で届く。`--push codex` だけ実行しても skill は古いままで、`--check codex` は clean と報告する。

| 指定された target | 実際に回すべき targets |
| --- | --- |
| `codex` / `opencode` / `pi` / `omp` | `<target>,shared-agents` |
| `claude` | `claude`（skill を自前の configDir に持つので単独で足りる） |

### --pull は 1 ターゲットずつ

`rules/` のように複数ターゲットが同じ source を共有している場合、全ターゲット一括 pull は事故になる。claude の live を SSOT に吸い上げた直後、codex が自分の古い live を drift と見なして同じ source へ書き戻す。`plan_pull` はターゲット間の競合検出も source の backup も行わないため、還流したい 1 ターゲットだけを指定する。

1 ターゲットを細かく見るときは `distribute.py` を直接使う:

```bash
"$(mise which python3)" scripts/distribute.py <target> --check    # exit 0 = in-sync / exit 1 = drift
"$(mise which python3)" scripts/distribute.py <target> --list     # 配布されるパス一覧（デバッグ用）
"$(mise which python3)" scripts/distribute.py <target> --push --dry-run
"$(mise which python3)" scripts/distribute.py <target> --push --prune   # manifest 外ファイルを backup して削除
"$(mise which python3)" scripts/distribute.py <target> --pull     # live → harness source へ還流（transform は skip）
```

メタ整合とドリフトをまとめて見るなら `./scripts/harness-doctor.sh`（前提ツール → `validate-harness.py` → `bootstrap.sh --check`）。

## config.json の読み方（現行スキーマ）

`distribute` は **`{配布先相対パス: {source, expandIncludes, transform}}` の dict**。

| キー | 意味 |
| --- | --- |
| dest_key | 配布先の相対パス。末尾 `/` = ディレクトリ宛て。source の実体（ファイル / ディレクトリ）と食い違えば fail fast |
| `source` | 文字列または配列。配列は記述順に重ね書き（後勝ち）。例: `rules/` は core + extras を統合 |
| `expandIncludes` | テンプレート中の include ディレクティブを `packages/core/fragments/` で展開。AGENTS.md 系がこれ |
| `transform` | SKILL.md の frontmatter を `skillsTransform.keepFrontmatterFields` の項目だけに削る。**現在の宣言は shared-agents のみ** |
| `settingsSync` | live の設定ファイルのうち宣言された `keys` だけを同期し、他キー（permissions のローカル蓄積等）は保持 |
| `obsoleteFiles` | 退役した配布物の掃除宣言。SSOT から消しただけでは live に残るため必ず宣言する |
| `executables` | 拡張子から実行ビットを判定できない配布物の明示宣言（`.sh` / `.py` は自動） |

`patches` / `applyPatches` は**廃止済み**（ADR-003 は 2026-07-26 に amended）。変換は `expandIncludes` と `transform` の 2 つだけ。

skill の除外は `packages/core/disabled-skills.json`（`common` + target キー）と extras 側の同名ファイルのみ。skill pack によるキュレーションは 2026-08-19 に廃止され、shared-agents は core + extras の全件を配る。

## curated skill（rulesync）は別経路

外部 upstream の skill は SSOT に vendoring せず rulesync が配る（ADR-011）。

| 項目 | 実体 |
| --- | --- |
| 宣言 | `rulesync.jsonc` / `rulesync.lock` |
| 配布 | `bootstrap.sh` の Step 2.5 → `~/.claude/skills` と `~/.agents/skills` |
| 実行条件 | **push のみ**。`--check` / `--pull` では走らない |
| 失敗時 | fail-closed（取得できなければ配布を止める） |

**`distribute.py --check` はこの層を見ない。** 全ターゲット OK でも curated の鮮度は保証されないので、`--check` の報告では「curated 層は未検査」と明示する。鮮度を確かめるなら:

```bash
GITHUB_TOKEN="$(gh auth token)" mise exec -- rulesync install --frozen   # lock と一致しなければ失敗
```

外部 skill を足すときは `rulesync.jsonc` に source を追記して `rulesync install`。`packages/core/skills/` にコピーしない。

## --push の出力の読み方

配布は台帳（`.harness-distributed.json`、ADR-008）で追跡する。

| 行 | 意味 |
| --- | --- |
| `added` / `updated` / `unchanged` | manifest と live の差分 |
| `mode fixed` | 実行ビットを補正した件数 |
| `removed obsolete` | `obsoleteFiles` 宣言による削除 |
| `removed managed stale` | 台帳が「harness が配った」と記録し、live の内容もその時のハッシュのまま残っていたので削除 |
| `preserved modified stale` | 台帳にはあるが live で手編集されていたので**消さずに残した**。SSOT-first 違反の疑いなので中身を確認する |

extras 未取得の dest は incomplete 扱いになり、`--prune` の削除対象から外れる。

## 孤児ファイル

配布先にあって manifest に無いファイルは `--push --prune` が backup のうえ削除する（管理ディレクトリ配下・source が完全に解決できた dest のみ）。集合演算を手で書かない。

## --pull

`distribute.py <target> --pull` が live → harness source の還流を行う（transform 対象は skip）。skill が上乗せするのは、スクリプトが見ない**未管理スキルの検出**:

```
local_skills   = ls ~/.claude/skills/ + ls ~/.agents/skills/
core_skills    = ls packages/core/skills/
extras_skills  = ls packages/extras/_active/skills/
curated_skills = rulesync.lock の sources[*].skills のキー
allowed_skills = packages/core/unmanaged-skills-allowlist.json のキー
unmanaged      = local_skills - core_skills - extras_skills - curated_skills - allowed_skills
```

`.githooks/pre-push` が同じ判定で push を block するので、判定条件を変えるときは両方を直す。

検出したら出自ごとに振り分ける:

| 出自 | 取り込み先 |
| --- | --- |
| `npx skills add` 等で入った外部 skill | `rulesync.jsonc` に source 追記 → `rulesync install`（vendoring しない） |
| 固有名・特定プロジェクト依存を含む自作 | `packages/extras/_active/skills/` |
| それ以外の自作 | `packages/core/skills/` |
| installer が scripts/ ごと入れるアプリ | `unmanaged-skills-allowlist.json` に理由付きで宣言 |

配置先の判定基準は ADR-002。core に入れる場合は `packages/core/commands.md` への登録も必要（validator が双方向チェックする）。

取り込み方法の選択は利用中のエージェントのユーザー確認機能で聞く（全件推奨通り / 個別選択 / スキップ）。

## 更新チェック（--update）

`--check` が「差分があるか」を答えるのに対し、`--update` は「どちらが新しいか」まで判定する。

1. `git fetch origin` して `origin/main` との位置関係を**報告する**（behind / ahead / diverged）。uncommitted changes と extras submodule の未 push commit も見る（`.githooks/pre-push` が block する条件と同じ）。このモードは読み取り専用で、fast-forward は行わない — cron から無人で走るため、作業ツリーを動かす操作はユーザーが承認してから別途実行する
2. `./scripts/harness-doctor.sh` を実行（前提ツール → `validate-harness.py` のメタ整合 → `bootstrap.sh --check` のドリフト）
3. curated 層を別途確認（上の節の `rulesync install --frozen`）
4. 差分の方向を判定する

判定の基準は git log ではなく**配布台帳** `<configDir>/.harness-distributed.json`（ADR-008）。台帳は「harness が最後に配ったときの各パスの SHA-256」を持つので、SSOT 側と live 側のどちらが台帳から動いたかで方向が確定する。git log は最後に配布した時点を知らず、未 commit の SSOT 編集も取りこぼす。

| カテゴリ | 判定材料（台帳のハッシュ基準） | アクション |
| --- | --- | --- |
| `harness-ahead` | SSOT が台帳と不一致、live は台帳と一致 | `--push` |
| `local-ahead` | live が台帳と不一致、SSOT は台帳と一致（= ライブ直編集） | `--pull` で還流（SSOT-first） |
| `conflict` | 両方が台帳と不一致 | 手動マージ。`~/.claude/backups/bootstrap-*/` も参照 |
| `in-sync` | `--check` が exit 0 | なし |

`--push` の出力に `preserved modified stale` が出ていた場合も `local-ahead` の兆候（台帳が手編集を検出して削除を見送った）。

定期実行したい場合は `/schedule create "0 9 * * *" "/sync-settings --update"`。

未解決の調査項目は `packages/targets/<target>/config.json` の `todoInvestigate` が唯一の一覧。

## commit / push は行わない

この skill は配布と還流だけを担当する。commit / push は破壊的・外部公開の操作なので、ユーザー確認の上で手動で行う:

- 新規 worktree は `EnterWorktree(name: <branch>)`（`WorktreeCreate` hook が `gwm add` を実行する）。main の checkout で `git switch -c` は block される
- stage は `git add <path>` で意図したファイルだけを指定する（`-A` で無関係な変更を巻き込まない）
- commit は単独のコマンドで実行する。他のコマンドと `&&` で連結すると `git-commit-chain` guard が拒否する
- push は `git push origin HEAD`、その後 `gh pr create`

push 前の品質ゲート（`/codex:review` を 1 回）は `rules/codex-review-policy.md` の担当。commit → push → 配布を 1 本化していた `scripts/publish.sh` と `/harness-publish` は 2026-08-28 に廃止した（配布先が 3 ターゲット固定で curated 層も走らず、`origin main` 直 push 前提が現行の PR 運用と噛み合わなかった）。配布は merge 後に `./scripts/bootstrap.sh` を回す。

## project マージモード（レガシー）

引数が `--check` / `--push` / `--pull` でなくパスの場合は、プロジェクト settings のマージとして動作する。

```bash
/sync-settings ~/projects/my-app
```

`[project-path]/.claude/settings.local.json` と `~/.claude/settings.json` の `permissions.allow` / `permissions.deny` 差分を提示し、インタラクティブにマージする。harness の配布とは無関係。

## 注意事項

- `--push` は live を上書きする。ライブ側の手編集は台帳が検出すれば保護されるが、**編集は必ず SSOT 側で行う**のが原則
- 設定ファイル本体（`settings.json` / `config.toml` / `opencode.json` / `config.yml`）は全部が同期対象ではなく、`settingsSync.keys` に宣言されたキーだけ。ローカル蓄積キーを守るための設計なので、同期したいキーが増えたら config.json 側に足す
- hooks は claude（`hooks/`）だけでなく pi（`claude-hooks/`）・opencode（`runtime/claude-hooks/`）にも配る。「hooks は Claude だけ」と判断しない
- `push` / `pull` は最初の失敗で中断する。`check` だけが全ターゲットを回しきる（モード表の下を参照）

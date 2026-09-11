# ADR-009: 開発 rigor profile による hook / policy の分類

## Status: Accepted

## Context

harness の分類軸は秘匿性（core / extras、ADR-002）と runtime 差（targets）の2つだけで、「どれだけ丁寧に回す開発か」という用途の軸が存在しなかった。その結果、codex-review ゲートや gwm worktree 強制のようなオーケストレーション規律が **runtime を proxy** にして配布されていた（Claude = 仕事、pi / opencode = 個人という現在の使い分けへの暗黙依存）。この proxy は両方向に漏れる: Claude Code で個人リポジトリを触ると全ゲートが個人開発に流入し、pi で丁寧に回したい開発をしてもゲートが無い。

2026-07-18 の OpenCode bridge（PR #14）で routing を guard 3本に絞った際、「codex review は Claude 専用でよい」「worktree 強制は個人用途に不要」という判断をしたが、これは runtime の性質ではなく開発の丁寧さの問題だった。

命名について: 「会社か個人か」は具体的すぎる。個人の本気プロジェクトを丁寧に回したいケースがあり、逆に仕事文脈でも使い捨てスクリプトはある。雇用主ではなく**開発の丁寧さ**で命名する。

## Decision

ポリシー（hook / rule / routing）は以下の4軸で分類する。新規ルール追加時は「どの軸に属すか」を先に決める。

| 軸 | 判定単位 | 機構 |
| --- | --- | --- |
| 1. baseline（どこでも適用） | 無条件 | 従来どおり全環境に配布・常時有効 |
| 2. rigor profile（`casual` / `rigorous`） | **リポジトリ** | `config.local` の `defaultProfile`（マシン単位の既定値）+ パスパターン → profile の上書きマップ。組織固有のパターンは extras から配布し、org 名を core に置かない（ADR-002 維持） |
| 3. モデル / runtime 特性 | **target** | 既存の targets routing（hooks.json / bridge の HOOKS 定数）。GPT-5.6 系 runtime にはハードゲートを積まない方針もここ |
| 4. 秘匿性 | ファイル配置 | core / extras（ADR-002。変更なし） |

### hooks の棚卸し（2026-07-18 時点）

**baseline** — casual でも有効:

- `block-dangerous-in-bash.sh`（git 安全は開発の丁寧さと無関係に必須）
- `block-grep-in-bash.sh` / `rtk-rewrite.sh`（トークン規律）
- `validate-prompt.sh`（警告のみ）
- `fix_gfm_tables.py` / `scan-new-skills.sh` / `log-compaction.sh`（整形・ユーティリティ）
- `check-plan-model.sh`（Claude 固有のモデル確認。害がない）
- `verify-before-commit.sh` / `verify-before-push.sh`（非ブロッキングのリマインダー。個人開発でも価値がある）

**rigorous のみ** — casual リポジトリでは発火しない:

- codex-review ファミリー一式: `block-pr-without-codex-review.sh` / `block-repeated-codex-review.sh` / `block-commit-without-difit.sh` / `set-codex-review-flag.sh` / `set-difit-flag.sh` / `difit-skip.sh` / `codex-review-bypass.sh` / `codex-review-reset.sh` / `codex-review-reminder.sh` / `lib/review-gate.sh` / `lib/review-router.sh`
- worktree 規律: `enforce-gwm-for-worktree.sh` / `block-edit-on-main.sh`
- PR 運用: `pr-desc-sync-check.sh`

**harness リポジトリ自体は casual** とする。gate は実運用で bypass が常態化しており（2026-07-17〜18 の PR #10 / #14 はいずれもユーザー指示 bypass）、品質担保は CI（unittest + validate-harness + shellcheck）が担っている。

### 実装方針（本 ADR の scope 外、後続 PR）

- `hooks/lib/` に profile 判定 lib を追加（`review-router.sh` と同じ「機械分類 lib + 消費 hook」パターン）。rigorous 分類の各ゲート hook は冒頭で判定し、casual なら即 exit 0
- pi の routing trim（`hooks.json` から codex-review 系と enforce-gwm を外し、OpenCode bridge と同じ guard 3本 + rtk-rewrite に揃える）は軸3（モデル / runtime 特性）の適用として実施
  - **2026-08-14 追記**: enforce-gwm-for-worktree.sh はこの trim を撤回し pi の Bash matcher に配線し直した。上記 lib/rigor-profile.sh が実装され block-edit-on-main.sh 同様 enforce-gwm-for-worktree.sh も casual で自己 exit 0 するようになったため、軸3（runtime routing）による暫定除外を維持する理由が無くなった。動機は pi の apply_patch が block-edit-on-main を素通りしたインシデントで、pi の Bash 経由 `git worktree add` 直叩きにも同じ穴があると分かったため。codex-review 系の trim は対象外（軸2 の自己判定が未実装のため据え置き）
- rules/*.md は paths ゲートによる非常駐化が既にあるため、本 ADR では分類対象外（必要になった時点で同じ4軸を適用する）

## Consequences

- 新規ルールの置き場所が「どの軸か」の一問で決まる
- runtime proxy が解消される: Claude Code で casual リポジトリを触ってもオーケストレーション系ゲートが発火しない。逆に将来 pi / opencode 側で rigorous 開発をしたければ routing を足せばよい
- 未分類リポジトリはマシンの `defaultProfile` に従う（仕事マシンは `rigorous`、個人マシンは `casual` を既定にする想定）
- 例外ケース（個人マシンで仕事リポジトリ等）は extras 配布のパターンマップが拾う。逆（仕事マシンで個人リポジトリ）は明示追加が必要
- profile 判定が実装されるまでの間、既存の挙動（全リポジトリでゲート有効）は変わらない

## 追補（2026-08-30）: profile 判定の実装完了

`packages/core/hooks/lib/rigor-profile.sh` と各 gate hook の profile 判定は実装済みである。したがって「本 ADR の scope 外、後続 PR」と「profile 判定が実装されるまでの間」という記述は当時の経緯として残すが、現行状態を表さない。harness リポジトリ自体を `casual` とする決定、および CI による品質担保は維持する。

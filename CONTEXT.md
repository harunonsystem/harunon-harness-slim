# harunon-harness

AI コーディングツール（Claude Code, Codex Desktop, OpenCode, pi, omp）の設定を一元管理する harness。

## ドメイン用語

| 用語 | 意味 |
| --- | --- |
| harness | このリポジトリ。全ツール共通の設定 SSOT |
| core | `packages/core/` — 汎用スキル・ルール・フック。OSS 化しても問題ない構成 |
| extras | `packages/extras/<codename>/` — 会社・プロジェクト固有のスキル・ルール。private submodule |
| target | 配布先runtime（claude, codex, opencode, pi, omp）またはshared-agents artifact（旧名 portable。ADR 本文の「portable」は同じもの）。`packages/targets/<name>/config.json` で定義 |
| distribute | config.json 内の宣言フィールド。SSOT から target に何を配布するかを記述し、その解決を `scripts/distribute.py` が実装する |
| distribution state | target の manifest、ledger、drift、source precedence と mutation plan を統合した、check / push / pull 時点の配布状態。 |
| distribution plan | distribution state が作る immutable な mutation operation と、plan 作成時点の source / destination 観測状態の組。dry-run と apply の共通入力。 |
| expandIncludes | config.json の distribute エントリのフラグ。`<!-- include: path -->` コメントを実ファイル内容に展開して配布する（`packages/core/fragments/agents-md/` の共有ブロックを各 target の薄い AGENTS.md テンプレートへ取り込むのに使う） |
| hookLibClosure | config.json の distribute エントリのフラグ。`<hooks dir>/lib/` 宛てにだけ付け、その親ディレクトリへファイル単位で配る hook 群が `$HOOK_DIR/lib/<name>.sh` で参照する lib の推移閉包（lib → lib も辿る）を resolver が計算して配布物に含める。hook が依存する lib を target ごとに手で列挙しない。参照先が無ければ manifest 生成で fail fast（`scripts/harness_lib/resolver.py` の `hook_lib_closure`） |
| configDir | 各runtimeの設定ディレクトリ（`~/.claude/`, `~/.codex/`, `~/.config/opencode/`, `~/.pi/agent`, `~/.omp/agent`）、またはshared-agents skillの`~/.agents/` |
| settingsSync | config.json の宣言フィールド。target の configFile（settings.json / config.toml / config.yml 等）のうち SSOT 管理キーだけを同期し、ローカル蓄積キーは保持する。local / extras overlay を持つ。実装は `scripts/harness_lib/settings_sync.py`（`compose` / `drifts` の 2 関数 interface。configFile を 1 つの論理ドキュメントとして「template seed → SSOT keys（+ removeKeys）→ local / extras overlay」の順に合成し、その層の並びは `_layers` 1 か所だけが持つ。distribution_state は `compose` が返す段を operation に写すだけで、合成順序やフォーマット差を知らない） |
| capability contract | `packages/core/capability-contract.json` にある runtime 間の能力比較 SSOT。`scripts/capability-bench.py` が target config の instruction runtime と static evidence を突合する。静的配線の証拠であり live 動作の保証ではない |
| AGENTS.md | Codex / OpenCode / pi / omp 用の指示ファイル。各 `packages/targets/<name>/AGENTS.md` が SSOT の薄型テンプレート（Claude の CLAUDE.md とは別ファイル系統）で、`expandIncludes` により `packages/core/fragments/agents-md/`（常駐ルール最小・Routing）を取り込んで配布時に生成する。CLAUDE.md からの機械変換ではない |
| dangerRules | 危険コマンドルールの SSOT table（`packages/core/policy/danger-rules.json`）。1ルール = 既定 action（block / confirm / warn）+ 方言併記の match（ere / globs / js）+ 意図的な runtime 差の overrides（理由必須）。shell hook・pi extension は runtime で読み、opencode / omp の glob は distribute が生成、散文は validator（`scripts/harness_lib/danger_rules.py`）が照合する。文脈依存ルールは `impl: "custom"` として手書きコード維持 + 台帳登録のみ。構造は `schemas/danger-rules.schema.json`、cross-field 制約は `danger_rules.py` |
| hookPipeline | runtime を跨いで共有される hook の実行順序・適用範囲の SSOT table（`packages/core/policy/hook-pipeline.json`）。dangerRules と同型で、1 hook = event + matcher（`when.tools` / `when.commandEre`）+ stage（guard / rewrite）+ order + `required` + 配線する runtime + 未配線 runtime の理由（`absent`、理由必須）。pi / omp / opencode は hookRunner が、codex は `codex_hook.py` が、この表を実行時に読んで hook を選ぶので、これら runtime に hook 一覧の実体は無い。validator（`scripts/harness_lib/hook_pipeline.py`）は配線した hook 実体が各 target の distribute 宣言で届くこと、hook 一覧がコードに再ハードコードされていないこと、claude の settings.json の membership を検証する。stage 順序（guard は rewrite より前）は逐次実行する runtime にのみ課し、並列実行の claude は membership だけ検証する |
| hookRunner | Claude PreToolUse hook（`packages/core/hooks/*.sh`）を Claude 以外の runtime で実行する共有 module（`packages/core/hook-runner/hook-runner.js`）。interface は `createHookRunner({ runtime }).preToolUse(toolName, toolInput, cwd) -> { decision, reason, finalInput, warnings }` の 1 本で、hookPipeline の実行時読み込み・wire protocol（stdin JSON / exit 2 / hookSpecificOutput / updatedInput 連鎖）・`required` hook の fail-closed・spawn の作法を内側に持つ。runtime ごとの adapter（pi: `pi-extensions/claude-hooks-bridge.ts`、omp: `omp-extensions/omp-denial-reason.js`、opencode: `opencode-plugins/claude-hooks-bridge.js`）は runtime のツール名 / 入力を Claude 名に写し、decision をホストの block / confirm / throw に写すだけ。配布レイアウト（`hook-runner/` の隣に `claude-hooks/` と `policy/`）が 3 runtime で同じ相対関係になる契約。post-edit（write / edit 後の shellcheck / jq / GFM）も同型で、`hook-runner/post-edit.js` が `post-edit-checks.sh` を呼び、adapter は path の取り出しと result への追記だけを持つ。codex は Python（`codex_hook.py`）が同じ table を読む第 2 実装で、hookProtocol の conformance fixture が adapter 差（確認 UI の有無・updatedInput の書き戻し）を divergence として宣言する |
| modelRouting | `runtime/role/purpose → model alias/effort → projection` の契約と current policy ledger（`packages/core/model-routing.json`）。portable な Skills / rules / AGENTS.md はモデル固有値を持たず、不変条件・境界・停止条件だけを持つ。model/provider/version の tuning は target adapter とこの台帳の edge に閉じ込め、`scripts/sync-model-routing.py` と `scripts/harness_lib/model_routing.py` が投影・drift・foreign model id を検証する。target の `config.json` は projection source を宣言する socket、`disabled-skills.json` は target 固有 skill の境界を宣言する。|
| assignment | Core Workflow の task state に持つ worker 割当（`state.assignments[]`、最後の要素が現在）。role（implement / review）・executor・workerId・status（assigned → dispatched → reported、または abandoned）・correlationId・subjectSha を持つ。同時 1 件。kernel の外に assignment の真実を持たない（ADR-012） |
| executor | assignment を実行する作業者 runtime（claude / codex / pi）。担える role は `policy/executors.json` が宣言し、kernel が照合する。起動方法は registry に書かず adapter の責務 |
| transport | worker 間通信の経路。現状 agmsg のみで `policy/transports.json` が場所を宣言し、`harness-doctor.sh` が存在確認する。kernel は transport を叩かず dispatch の事実だけ記録する |
| correlationId | assignment 作成時に kernel が発行し、dispatch する message 本文の先頭に埋める鍵。agmsg に thread が無いため、worker の返信を assignment に紐づける手段を transport 非依存に持つ |
| worker report | worker の完了報告 evidence（`kind: worker-report`, `trust: audit-only`）。executor / workerId / subjectSha / resultSha / artifact / checks を持つ。coordinator が検収して `assignment.report` で state に入れる（worker は直接書かない） |
| hookProtocol | Claude PreToolUse の wire protocol を runtime 横断で固定する conformance 契約（`scripts/tests/fixtures/hook-protocol.json`）。同じ fixture を pi / opencode / omp の adapter と Codex の第2実装に流し、正規化した結果（allow / deny / ask / rewrite）が宣言と一致することを `scripts/tests/node/hook-protocol-conformance.test.ts` が確認する。ホスト能力差による runtime 差は `divergence` として理由付きで宣言し、黙って揃うのも黙ってズレるのも落とす。実行時に読まれないため `policy/` には置かない（配布対象外） |

## アーキテクチャ

```
packages/core/ (SSOT)
    ├── CLAUDE.md, RTK.md, commands.md
    ├── rules/        ← ポリシー群
    ├── skills/       ← スキル群
    ├── policy/       ← runtime 非依存の Policy Kernel
    ├── workflows/    ← Core Workflow と task state schema
    ├── hooks/        ← フック群（Claude Code 用。pi / omp / opencode / codex も hookRunner 経由で無改修実行）
    ├── hook-runner/  ← hookRunner（hooks/*.sh を Claude 以外の runtime で実行する共有 module + post-edit）
    ├── agents/       ← Claude Code サブエージェント定義
    ├── pi-extensions/ ← pi 用 extension（hooks bridge adapter, confirm-destructive, providers 等。post-edit-checks.js は omp と共有）
    ├── omp-extensions/ ← omp 専用 extension（omp-denial-reason adapter）
    ├── opencode-plugins/ ← opencode 用 runtime module（umbrella plugin が合成。hooks bridge adapter 等）
    ├── fragments/
    │   └── agents-md/ ← AGENTS.md 系（codex/opencode/pi/omp）が expandIncludes で共有する常駐ブロック
    ├── settings.json ← テンプレート
    └── capability-contract.json ← runtime capability comparison SSOT

packages/extras/_active/ (private submodule)
    ├── rules/        ← プロジェクト固有ポリシー
    └── skills/       ← プロジェクト固有スキル

packages/targets/
    ├── claude/config.json    ← 変換なし（SSOT そのもの。CLAUDE.md をそのまま配布）
    ├── codex/config.json     ← 薄型 AGENTS.md（expandIncludes）+ agents/ サブエージェント + settingsSync
    ├── opencode/config.json  ← 薄型 AGENTS.md（expandIncludes）+ permission-overlay.json settingsSync
    ├── pi/config.json        ← 薄型 AGENTS.md（expandIncludes）+ settings.json settingsSync + claude-hooks bridge + Core Workflow native gate
    └── omp/config.json       ← 薄型 AGENTS.md（expandIncludes）+ config.yml settingsSync
```

## 配布フロー

```
bootstrap.sh                    → DEFAULT_TARGETS 全 target（shared-agents / claude / codex / opencode / opencode-launcher / pi / omp）へ一括配布
bootstrap.sh --targets codex    → 特定ターゲットのみ配布
bootstrap.sh --check            → 全ターゲットのドリフト検出（書き込まない）
bootstrap.sh --pull             → live 側の手元修正を harness へ還流
```

全ツールへの配布はファイルコピーで行う（symlink は使わない）。`bootstrap.sh` は `scripts/distribute.py` の殻であり、各 target の `packages/targets/<name>/config.json` が唯一の真実（SSOT-first）。AGENTS.md の生成（`expandIncludes` によるフラグメント展開）を含む全配布処理を `distribute.py` が決定論的に行う。

## 編集フローの原則（SSOT-first）

**編集は必ず harness（このリポジトリ）側で行い、ターゲットへは配布する。** ライブ側（`~/.claude/` 等）の直接編集は緊急ホットフィックスに限り、その場合は**即日 harness に還流**する。還流しないまま bootstrap / sync-settings --push を実行すると、ライブ側の修正は backup 退避のうえ SSOT の古い内容で上書きされる（実例: codex review コマンドのモデル設定が巻き戻った 2026-06-11 のインシデント）。

ガード:
- pre-push がライブ ↔ SSOT のドリフトを distribute 全カテゴリで警告
- bootstrap が上書き発生時に件数と backup 先を警告（還流要否の確認を促す）
- 巻き戻してしまった場合は `~/.claude/backups/bootstrap-*/` から復元して還流する（backup は最新 10 件保持）
- settings.json は settingsSync 宣言（claude target）で hooks / sandbox / permissions.deny・ask / autoMode 等の宣言キーだけ同期・drift 検出。permissions.allow 等のローカル蓄積キーは触らない。autoMode（auto-mode classifier の散文ルール）は danger-rules.json の `rule.autoMode` から `scripts/sync-auto-mode-rules.py` が投影する生成物で、validator が一致を強制する。sandbox は security 設定のため SSOT 同期対象（excludedCommands に docker/gh/gcloud/terraform を含むのは Go 製 CLI の TLS 検証がサンドボックス配下で失敗する既知の非互換のため）
- SSOT 側で削除・リネームしたファイルのライブ側削除は `--push --prune`（オプトイン。backup して削除）

## core / extras 分離基準

| 該当するなら | 配置先 |
| --- | --- |
| 会社名・org 名・社内サービス名が出てくる | extras |
| 特定プロジェクトのパス構造に依存する | extras |
| 特定フレームワークの固有規約に依存する | extras |
| 上記いずれにも該当しない | core |

迷ったら extras。core は汚染しない。

## 現在の管理規模

| カテゴリ | core | extras |
| --- | --- | --- |
| skills | 28 | 9 |
| rules | 5 | 7 |
| hooks | 36 (35 shell + 1 python) | — |
| ADRs | 13 | — |

外部 skill（rulesync が upstream から配る分。`rulesync.lock` が宣言元、claude / shared-agents の distribute[skills/].source `.rulesync/skills/.curated/` 経由で distribution ledger が管理）はこのカウントに含めない。SSOT に vendored コピーを持たず、upstream を正本とする。

## ツール間の差異

| 項目 | Claude Code | Codex Desktop | OpenCode | pi | omp |
| --- | --- | --- | --- | --- | --- |
| 指示ファイル | CLAUDE.md | AGENTS.md | AGENTS.md | AGENTS.md | AGENTS.md |
| config | settings.json | config.toml | opencode.json | settings.json | config.yml |
| configDir | `~/.claude/` | `~/.codex/` | `~/.config/opencode/` | `~/.pi/agent` | `~/.omp/agent` |
| skills 配布 | コピー (bootstrap) | `~/.agents/skills`（shared-agents）を参照 | `~/.agents/skills`（shared-agents）を参照 | `~/.agents/skills`（shared-agents）を参照 | include 2 件のみコピー（他は `~/.agents/skills` 参照） |
| hooks | shell script | `harunon-core` Codex plugin（codex_hook.py が hook-pipeline.json を読む） | umbrella plugin の claude-hooks-bridge.js（adapter）→ runtime/hook-runner/（hookRunner）→ runtime/claude-hooks/。required hook 未配布は fail-closed | extensions/claude-hooks-bridge.ts（adapter）→ hook-runner/（hookRunner）→ claude-hooks/ | config.yml bash.patterns（deny 主体）+ extensions/omp-denial-reason.js（adapter）→ hook-runner/ → claude-hooks/block-dangerous-in-bash.sh（deny 理由の説明） |
| rules 配布 | コピー (bootstrap) | コピー (sync-settings) | コピー (bootstrap) | コピー (bootstrap) | コピー (bootstrap) |

# ADR-010: Codex / pi / omp の Sol・Luna ルーティング

## Status: Accepted (Amended 2026-09-10)

## Context

GPT-5.6 の利用可能な期間は契約に依存する。一方で、設計・レビューと実装・スクリプトでは必要な性質が異なるため、target ごとにモデル名を直接散らすと、Terra の再混入、推論レベルの不一致、live 設定だけの修正が起きやすい。

## Decision

ハーネスの標準ルーティングを次のモデルに限定する。

| 用途 | モデル | reasoning / thinking |
| --- | --- | --- |
| 設計、計画、レビュー | `gpt-5.6-sol` | `medium` |
| Codex / omp の親タスク（default）、実装、スクリプト、探索、subtask | `gpt-5.6-luna` | `max` |
| pi の親タスク（default） | `gpt-5.6-luna` | `medium` |
| pi の実装、スクリプト、探索、subtask | `gpt-5.6-luna` | `max` |

target ごとの対応は以下のとおり。

- Codex: default は Luna max。`review_model` と `reviewer` は Sol medium、`subagent-default` / `explorer` / `worker` は Luna max。Astra は標準ルートに置かず、必要なときに picker で手動選択する（理由は Amendment 2026-09-10 の追記）。
- pi: default は Luna medium。`planner` / `reviewer` は Sol medium、`scout` / `worker` は Luna max。Codex conversion の設定と extension package は SSOT から配布する。
- omp: 全 role（`default` / `slow` / `plan` / `smol` / `task` / `commit`）は Luna max。`openai-codex/*` は有効化する。

Terra は標準ルートに置かない。OpenAI Codex OAuth が失敗・期限切れになっても、別 provider へ自動 fallback しない。品質・コスト・契約状態の変化を暗黙に混ぜず、明示的な操作として記録する。

認証情報、OAuth token、サブスクリプション状態は SSOT に保存しない。Pi / OMP の Zen 系モデルは明示的な緊急 fallback 用に有効化してよいが、通常ルート・role・retry chain には登録しない。

## Amendment (2026-07-24): Codex / pi の default を Luna に変更

当初の決定では親タスク（default）も Sol medium だったが、live 側で先行運用していた設定を SSOT に還流し、Codex の default を Luna xhigh、pi の default を Luna max に変更した。設計・計画・レビュー役（Codex `review_model` / `reviewer`、pi `planner` / `reviewer`）は Sol medium のまま。omp は据え置き（`default` / `slow` / `plan` は Sol medium）。上の Decision は改定後の内容に更新済み。

## Amendment (2026-08-11): Codex の model / effort 所有権を再定義

Codex target の設定は 2 つの所有権平面に分かれることが判明したため、default の値変更ではなく所有権の再定義として改定する。

1. **SSOT-owned**（push 同期）: `model_provider` / `review_model` / features / agents 等の方針・機能キー。従来どおり `settingsSync.keys` で同期する。
2. **SSOT-owned**: `model` / `model_reasoning_effort` / `plan_mode_reasoning_effort`。Codex app 再起動時に medium へ戻るため、`keys` で push 同期し、`gpt-5.6-luna` / `max` を強制する（xhigh の例外は廃止し Luna は max に統一）。app composer の新規 thread デフォルトも config.toml の値から seed される。

Codex CLI / exec / subagent / review は従来どおり config.toml と profile / agents toml を読むため、役割別ルーティング（Sol medium = 設計・レビュー、Luna max = 実装・探索）の保証はこの改定で変わらない。

## Amendment (2026-08-15): machine-local catalog workaround の撤回

`model_catalog_json` を SSOT/local overlay で管理する方針を撤回する。Codex の custom catalog は bundled catalog 全体を置き換えるため、モデル一覧を固定すると更新後のメタデータが stale になる。`config.toml` の `model_reasoning_effort = "max"` と `plan_mode_reasoning_effort = "max"` を同期する既存の SSOT 経路だけを正とする。

そのため `model_catalog_json` は `localKeys` から削除し、`removeKeys` に追加する。bootstrap は pinned catalog を生成・更新せず、次回の push で既存 live 設定からキーを削除する。

## Amendment (2026-08-20): omp の slow / plan を Luna max に変更

omp の `slow` / `plan` を Sol medium から Luna max に変更し、omp は全 role Luna max に統一する。設計・レビューを Sol medium に分ける役割ルーティングは Codex（`review_model` / `reviewer`）と pi（`planner` / `reviewer`）に残る。契約面（`packages/targets/omp/AGENTS.md` のロール活用節・`config.json` の notes）も同時に更新し、prose と `config.yml` の role 実体の整合は `test_model_routing.py` が検証する。上の Decision は改定後の内容に更新済み。

## Amendment (2026-08-30): pi の default を Luna medium に下げる

pi の `defaultThinkingLevel: max` は main セッションの毎ターンに最大推論を掛けており、小さな修正に 1 時間半かかる実例が出た。main は計画・統合・検収に徹する役なので最大推論は要らないと判断し、default を Luna medium に下げる。observational-memory の reflector も同じ理由で xhigh から low にする。

重い推論は `scout` / `worker`（Luna max）への委譲で確保する。`planner` / `reviewer` の Sol medium は据え置く。main を下げた分を Sol 側の thinking level 引き上げで埋める案は、症状（main が遅い）と因果が無く Sol の消費を増やすだけなので採らない。

変更対象は pi だけで、Codex（Luna max）と omp（全 role Luna max）の default は据え置く。上の Decision の pi 行は改定後の内容に更新済み。

## Update 2026-09-03: 決定を machine-readable な table に移す

上の Decision と各 Amendment が決めた役割別割当は、`packages/core/model-routing.json`（CONTEXT.md の modelRouting）に 1 route = runtime + role + purpose + model + effort として置いた。ルーティングの内容は一切変えていない。変えたのは真実の置き場所だけである。

- これまで割当は codex の `config.toml` / `agents/*.toml` / `profiles/*.toml`、pi の `settings.json` / `agents/*.md`、opencode の `agents/reviewer.md`、omp の `config.yml` に散らばり、`scripts/tests/test_model_routing.py` の文字列一致アサートだけが束ねていた。改定のたびに宣言とテスト期待値を両方書き換え、テストが値に後追いするだけの回もあった（c62aaad）
- 以後、宣言ファイルは table の投影（生成物）として扱う。`scripts/sync-model-routing.py` が該当キーの値だけを書き込み、`scripts/harness_lib/model_routing.py`（validate-harness の `model-routing` check）が一致と、table 外の model id（Terra 等）の再混入を拒否する
- 既定（design = Sol medium / build = Luna max）から逸脱する route（pi default の Luna medium、omp slow / plan の Luna max）は table に `reason` を持ち、上の Amendment を参照する。逸脱理由が散文だけでなく表に残る
- この ADR を改定するときの手順: table を直す → `scripts/sync-model-routing.py` → この ADR に Amendment を書く。宣言ファイルを直接編集しない

## Amendment (2026-09-10, 同日撤回): Codex の親タスクを Astra xhigh に変更 → Luna max へ差し戻し

**この改定は同日に撤回した。** 撤回理由を先に書く（下の当初根拠は判断の記録として残す）。

Astra は 5.6 系と同じ rate limit の窓では回らず、**plan の included allowance を引く別枠**で動く。team / Business Standard plan では **5h あたり 5〜45 local messages** で、default に据えると親タスクが数セッションで枠を使い切る。実測では Astra 2 セッション（計 50 turns）を回した時点で `workspace_member_credits_depleted` に到達し、以降のリクエストが止まった。そのとき 5h 窓は 70%・週窓は 45% が残っており、**luna / sol の枠とは別勘定であることが確認できた**（2026-09-10 実測）。

当初根拠にした社内実測「低い effort は試行回数を増やして総消費を上げる」はトークン数の話であり、Astra の allowance はメッセージ数と compute でカウントされる。公式も「higher reasoning effort means the model spends more compute」と明言しているため、**xhigh は allowance の消費を速める方向**だった。軸を取り違えて繋げたのが誤りである。

したがって:

- `codex/default` は Luna max に戻す。`models` から `astra` alias を外す（どの route も使わないため）
- Astra は必要なときに picker で手動選択する。用途は「答えがある / 問いの質が高い」場面に限る
- plan を上げる（Pro $100 で 25〜225 msgs、Business Premium は 5h 制限なし）か API key の従量課金に切り替えるなら、この判断は再検討の対象になる。今日の実測を API 課金に置き換えた試算は Astra 2 セッションで約 $8.4（うち $4.6 は cached input）

## 当初の根拠（2026-09-10、撤回済み）

Codex の `default` を Luna max から `gpt-6-astra` の xhigh に変更し、table の `models` に `astra` を追加する。

根拠:

- rollout ログ 611 セッションの実測で、Codex 消費 2,758M トークンのうち input が 99.6%、その 95.3% が cached input（同じ文脈の読み直し）。reasoning output は 0.12% しかない。**effort を下げてトークンを節約する経路は存在しない**
- 低い effort は 1 ターンを安くする代わりに試行回数を増やし、セッション総消費を上げる（社内実測。Astra では 5.6 系より顕著に出る）
- GPT-6 Astra は GPT-5.6 Sol の上位（DeepSWE v1.1 で 74.1% vs 72.7%）で、Codex 内では cached input が課金されず 272K 超の long-context 倍率も付かない
- Astra の公式 default reasoning level は `low`（`codex debug models` の実効値。2026-09-10 実測）。xhigh はそこから 3 段上げた逸脱で、根拠は上記の「低い effort は試行回数を増やして総消費を上げる」という社内実測にある。公式 default が速度とコストのバランスを見ているのに対し、こちらは総トークンを見ているので軸が違う

適用範囲は codex の `default`（親タスク）だけ。`subagent-default` / `explorer` / `worker` は Luna max、`review` / `review-high` / `reviewer` は Sol medium を維持する。Astra は答えがあるとき・問いの質が高いときのまとめ役で、機械的な実装や探索に単価 10 倍のモデルを充てる理由がない。

未解決（この改定では触らない）:

- `model_context_window` / `model_auto_compact_token_limit` は 272000 / 240000 で確定。`codex debug models` の実効値で **Astra の context_window は 272000**（5.6 系と同じ）と確認したため、外部で報じられていた 1M ウィンドウは Codex 内では当てはまらない。ウィンドウを広げる検討自体が不要（2026-09-10 実測、codex-cli 0.153.4。bundled catalog の 2026-07-21 スナップショットには Astra が無く、当初この値を確認できていなかった）
- pi / omp の default は据え置き。pi は Amendment 2026-08-30 で Luna medium に下げたが、その根拠（「Sol 側の thinking level 引き上げは Sol の消費を増やすだけ」）は上記の実測と食い違うため再検証が必要

## Subscription termination runbook

OpenAI Codex を使えなくなった時点で、次の順に実行する。

1. `./scripts/harness-doctor.sh --targets pi,omp` で認証欠落と配布ドリフトを確認する。
2. Pi は `pi --model opencode-zen/mimo-v2.5-free`、OMP は `omp --model opencode-zen/mimo-v2.5-free` のように、明示したセッションだけ fallback provider を使う。
3. 継続利用する場合は、fallback provider / model / thinking level を選び、SSOT の各 target 設定とこの ADR を更新する。live 側だけを編集しない。
4. `./scripts/bootstrap.sh` または `/sync-settings --push pi|omp` で配布し、`--check` と回帰テストを通す。

Codex Desktop は OpenAI provider を既定にしているため、契約終了時は Codex 固有の利用可能 provider（またはローカル provider）を先に選定してから target SSOT を変更する。自動的に別契約へ切り替えない。

## Consequences

- 設計・レビュー（Sol medium）と実装・探索（Luna max）の分離が 3 target で共通になり、Terra の再混入をテストで検出できる。ただし Codex の親タスクだけは Astra xhigh に分かれるため（Amendment 2026-09-10）、3 target の割当は完全に同一ではない。
- Sol の品質を設計・レビューに、Luna の高スループットを実装系に集中できる。Codex の親タスクは Astra の到達点の高さを取り、単価 10 倍のモデルを親タスク 1 role に閉じ込める。
- OpenAI 契約が無くなった場合に作業が突然別モデルへ流れず、明示的な切替が必要になる。
- 代替 provider は事前に候補を有効化できるが、可用性・品質・料金の確認は切替時に再検証する。

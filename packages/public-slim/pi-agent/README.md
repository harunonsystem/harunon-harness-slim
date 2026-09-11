# harunon-pi-agent-slim

[pi coding agent](https://github.com/badlogic/pi-mono) の設定ディレクトリ（`~/.pi/agent`）に配る payload だけを切り出した配布物です。
ルートがそのまま pi の configDir の中身で、他ランタイム（Claude Code / Codex / OpenCode）の設定や配布機構は持ちません。

このリポジトリは **生成物** です。SSOT は `harunon-harness`（private）で、`harunon-harness-slim` を経由して
`scripts/build-public-slim.py` が組み立てています。ここで直接編集した内容は次の生成で巻き戻るので、変更は SSOT 側に還流してください。

## 使い方

pi 本体は別途インストールします（npm / mise など。バージョンは各自の環境で pin してください）。

```bash
./scripts/validate.sh                 # 静的検証（JSON / shell / JS / Python / 資格情報スキャン）
./scripts/install.sh --dry-run        # ~/.pi/agent に何が変わるかを表示
./scripts/install.sh                  # 配布
./scripts/install.sh --check          # 配布後のドリフト確認（差分があれば exit 1）
```

`install.sh` は `install-manifest.json` の `managedPaths` だけを rsync し、`settings.json` は `settingsKeys` に挙がったキーだけを既存ファイルへマージします。
`auth.json`・アカウント状態・ローカル専用キーは触りません。配布先は `--dest DIR` か環境変数 `PI_AGENT_DIR` で変えられます。

## 構成

- `AGENTS.md` — pi に常時読ませる最小指示（共有 fragment を展開済み）
- `settings.json` — pi の runtime 設定（同期キーは `install-manifest.json` 参照）
- `agents/` — subagent 定義（scout / planner / worker / reviewer）
- `extensions/` — hook bridge・破壊的操作の確認・provider・Core Workflow の hard gate
- `hook-runner/` — runtime 共有の hook 実行器（`policy/hook-pipeline.json` を読んで hook を選ぶ）
- `claude-hooks/` — bridge から Claude PreToolUse プロトコルで呼ぶ安全 hook
- `policy/` / `workflows/` — 危険コマンド表・hook 配線表・Core Workflow の状態機械
- `rules/` — 必要時に読む開発・レビュー規約
- `commands.md` — skill の索引

skill 本体は同梱しません。pi が読む共通 skill は `~/.agents/skills` に置き、同名 skill の二重配布を避けます（`harunon-harness-slim` の `shared-agents` target が配ります）。

## 前提ツールについて

- `jq` と `rsync` は install に必須です
- `claude-hooks/rtk-rewrite.sh` は rtk（コマンド出力を圧縮する CLI）が無ければ何もせず素通りします（任意）
- `claude-hooks/enforce-gwm-for-worktree.sh` は worktree 作成を gwm（worktree 管理 CLI）経由に強制します。gwm を使わない場合は rigor profile を `casual` にするか、`policy/hook-pipeline.json` からこの hook の `pi` 配線を外してください

## 境界

認証情報、OAuth token、`auth.json`、`openai-codex-accounts.json`、provider の API key は保存・commit しません。
モデル定義には credential の参照先だけを書きます。`scripts/validate.sh` が credential らしき文字列を検出したら失敗します。

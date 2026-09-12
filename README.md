# harunon-harness-slim

複数の AI コーディングエージェントに同じ skills・rules・安全 hook・subagent 定義を配るためのハーネスです。
各ランタイムの設定ディレクトリへそのまま置ける完成形（payload）を target ごとに収め、`scripts/install.sh` が配布します。

## 構成

| ディレクトリ | 配布先 | 内容 |
| --- | --- | --- |
| `claude/` | `~/.claude` | Claude Code 用の CLAUDE.md・skills・rules・hooks・agents・commands・settings.json |
| `codex/` | `~/.codex` | Codex 用の AGENTS.md・rules・Codex 専用 skills・config.toml・review 用 config |
| `opencode/` | `~/.config/opencode` | OpenCode 用の AGENTS.md・agents・plugins・runtime・opencode.json |
| `opencode-launcher/` | `~/.local/bin` | OpenCode を安全設定付きで起動する `opencode` ラッパー（PATH で本体より前に置く） |
| `omp/` | `~/.omp/agent` | oh-my-pi 用の AGENTS.md・extensions・hook-runner・policy・config.yml |
| `pi/` | `~/.pi/agent` | pi coding agent 用の AGENTS.md・agents・extensions・hook-runner・policy・settings.json |
| `shared-agents/` | `~/.agents` | Codex / OpenCode / omp / pi が共通に読む skills・policy・workflows |

各 target ディレクトリの `install-manifest.json` に、配布先（`configDir`）・管理パス（`managedPaths`）・設定ファイルの同期方法が書いてあります。
skills は Claude 以外のランタイムには `shared-agents/` から 1 回だけ配り、各ランタイムの configDir には複製しません。

## インストール

```bash
scripts/validate.sh                       # 静的検証（JSON / shell / JS / Python / 資格情報スキャン）
scripts/install.sh claude --dry-run       # ~/.claude に何が変わるかを表示（書き込みなし）
scripts/install.sh claude                 # 配布
scripts/install.sh claude --check         # 配布後のドリフト確認（差分があれば exit 1）
```

`claude` の部分を `codex` / `opencode` / `opencode-launcher` / `omp` / `pi` / `shared-agents` に替えて、使うランタイムの分だけ実行します。
配布先は `--dest DIR` で変えられます。

`install.sh` は `managedPaths` だけを rsync し、配布先にある未管理ファイルは触りません。
配ったファイルは配布先の `.harunon-slim.installed.json` に記録し、次回は「前回配ったが今回の payload に無いファイル」だけを消します。
上書き・削除される既存ファイルは配布先の `.harunon-slim.backups/<timestamp>/` に退避するので、手で編集していた CLAUDE.md 等はそこから取り戻せます。
`codex/` は環境変数 `CODEX_HOME` が設定されていればそこへ配ります（`install-manifest.json` の `configDirEnv`）。

## 設定ファイルの扱い

- JSON（`claude/settings.json`・`opencode/opencode.json`・`pi/settings.json`）: 既存ファイルがあれば `install-manifest.json` の `settingsKeys` に挙がったキーだけをマージし、それ以外のローカル値は保持します。無ければファイルごと置きます
- TOML / YAML（`codex/config.toml`・`omp/config.yml`）: 配布先に無いときだけ置きます。既にある場合は触らず `S config.toml (not merged: toml; ...)` と知らせるので、その target の `install-manifest.json` にある `settingsKeys` のキーを手で取り込んでください

## 前提ツール

- `jq` と `rsync`（`install.sh`）。`validate.sh` はさらに `node` と `python3` を使います
- hook は `node`（hook-runner）と `python3`（policy）で動きます。skill の一部（`skill-creator` の検証スクリプト）は `python3` に PyYAML が入っていることを前提にします
- `rtk-rewrite.sh` は rtk（コマンド出力を圧縮する CLI）が無ければ何もせず素通りします（任意）
- `enforce-gwm-for-worktree.sh` は worktree 作成を gwm（worktree 管理 CLI）経由に強制します。gwm を使わない場合は rigor profile を `casual` にするか、`policy/hook-pipeline.json` からこの hook の配線を外してください

## 境界

認証情報、OAuth token、provider の API key は含めません。モデル定義には credential の参照先だけを書きます。
`scripts/validate.sh` が credential らしき文字列を検出したら失敗します。

## このリポジトリについて

このリポジトリは SSOT から生成された成果物です。ここで直接編集した内容は次の生成で巻き戻るので、変更は SSOT 側に還流してください。

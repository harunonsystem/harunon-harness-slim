# harunon-harness-slim

複数のAIコーディングエージェントへ、共通のskills・rules・安全hookとruntime別の設定を配布します。
各runtimeの設定一式をtargetごとのディレクトリに収めています。`scripts/install.sh`で設定ディレクトリへインストールできます。

## 構成

| ディレクトリ | 配布先 | 内容 |
| --- | --- | --- |
| `claude/` | `~/.claude` | Claude Code 用の CLAUDE.md・skills・rules・hooks・agents・commands・settings.json |
| `codex/` | `~/.codex` | Codex 用の AGENTS.md・rules・Codex 専用 skills・config.toml |
| `opencode/` | `~/.config/opencode` | OpenCode 用の AGENTS.md・agents・plugins・runtime・opencode.json |
| `opencode-launcher/` | `~/.local/bin` | OpenCode を安全設定付きで起動する `opencode` ラッパー（PATH で本体より前に置く） |
| `omp/` | `~/.omp/agent` | oh-my-pi 用の AGENTS.md・extensions・hook-runner・policy・config.yml |
| `pi/` | `~/.pi/agent` | pi coding agent用のAGENTS.md・extensions・hook-runner・policy・settings.json |
| `shared-agents/` | `~/.agents` | Codex / OpenCode / omp / pi が共通に読む skills・policy・workflows |

各targetの`install-manifest.json`に、配布先の`configDir`、管理パスの`managedPaths`、設定ファイルの同期方法を記載しています。
Claude以外のruntimeが使う共通skillsは、`shared-agents/`から1回だけ配布します。Codex専用skillsは別途`codex/`から配布します。

## インストール

```bash
scripts/validate.sh                       # 静的検証（JSON / shell / JS / Python / 資格情報スキャン）
scripts/install.sh claude --dry-run       # ~/.claude に何が変わるかを表示（書き込みなし）
scripts/install.sh claude                 # 配布
scripts/install.sh claude --check         # 配布後のドリフト確認（差分があれば exit 1）
```

`claude`の部分を使うtarget名に替えて実行してください。Codex / OpenCode / omp / piを使う場合は、`shared-agents`もインストールします。
配布先は`--dest DIR`で指定できます。

`install.sh`は`managedPaths`にあるファイルだけをrsyncで配布し、未管理のファイルは変更しません。
配布済みのファイルは`.harunon-slim.installed.json`に記録します。次回の配布では、前回配ったファイルのうち、今回の配布物にないものだけを削除します。
上書き・削除する既存ファイルは`.harunon-slim.backups/<timestamp>/`に退避します。手元の修正はそこから復元できます。
Codexの配布先は、`CODEX_HOME`が設定されていればそのディレクトリになります。

## 設定ファイルの扱い

JSON（`claude/settings.json`・`opencode/opencode.json`・`pi/settings.json`）は、既存ファイルがあれば`install-manifest.json`の`settingsKeys`にあるキーだけをマージします。それ以外のローカル値は保持し、ファイルがなければ全体をコピーします。

TOML / YAML（`codex/config.toml`・`omp/config.yml`）は、配布先にないときだけコピーします。既にある場合は変更せず、`S config.toml (not merged: toml; ...)`と表示します。該当targetの`install-manifest.json`にある`settingsKeys`のキーを手で取り込んでください。

公開設定は安全hookと共通機能に必要なキーだけです。モデル、UI、個人用plugin / npm packageは指定しません。既存の値は保持し、新規環境ではruntimeの既定値を使います。

## 前提ツール

`install.sh`には`jq`と`rsync`、`validate.sh`にはさらに`node`と`python3`が必要です。hookもhook-runnerに`node`、policyの処理に`python3`を使います。`skill-creator`の検証スクリプトなど、一部のskillにはPyYAMLが必要です。

コマンド出力を圧縮するCLIのrtkは任意です。未導入の場合、`rtk-rewrite.sh`はコマンドを変更せずに通します。

worktreeはruntimeの標準機能かGitで作成できます。gwmは必須ではありません。共有checkoutの保護や破壊的操作の確認hookは残しています。

外部skillは自動取得しません。`tdd` / `diagnosing-bugs`が未導入でも、rulesにあるテスト先行・根本原因調査の手順で進められます。Issue trackerはプロジェクト設定と入力URLに従います。

## 境界

認証情報、OAuth token、providerのAPI keyは含めません。モデル定義に記載するのはcredentialの参照先だけです。
`scripts/validate.sh`は、credentialらしき文字列を検出すると失敗します。

## このリポジトリについて

このリポジトリはSSOTから生成した配布物です。ここで直接編集した内容は次の生成で上書きされるため、継続して使う変更はSSOT側へ取り込んでください。

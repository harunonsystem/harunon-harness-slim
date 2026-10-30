# harunon-harness-slim

複数のAIコーディングエージェントへ、共通のskills・rules・安全hookとruntime別の設定を配布します。
各runtimeの設定一式をtargetごとのディレクトリに収めています。

---

## クイックスタート（おすすめ）

### 🤖 エージェントにお任せ導入
Claude Code などのエージェントを立ち上げ、このリポジトリを見せながらこう伝えてください：

> **「この README を読んで、対話しながら harunon-harness-slim をセットアップして」**

エージェントが現在の環境を探索し、**「おすすめフルパック（思考モードON＋安全コマンド自動許可）」** か **「ガードレールのみ」** かを選択肢で質問しながら、自動でセットアップを完了します。

### 💻 ターミナルから対話で導入
```bash
# 対話式ウィザードで導入（質問に答えるだけ / Enter連打で推奨値）
scripts/setup.sh

# または一発導入（Claude Code に推奨フル設定を一括適用）
scripts/setup.sh --target claude --preset recommended
```

---

## エージェント向け導入プロトコル

AI エージェント（Claude Code 等）がユーザーから「README を見ながら導入して」と依頼された場合、以下のプロトコルに従ってください。

1. **現状の探索（Explore）**:
   - 使用しているランタイム（Claude Code: `~/.claude`, Codex: `~/.codex` 等）と既存設定ファイルの有無を確認する。
2. **選択肢のヒアリング（Ask & Options）**:
   - ユーザーに質問し、導入対象ターゲット（既定: `claude`）と導入プロファイルを選択してもらう：
     - **[1] おすすめフルパック (推奨)**: 安全ガードレール ＋ 思考モード (Thinking: medium) ＋ 安全コマンド自動許可 ＋ 日本語設定
     - **[2] ガードレールのみ**: 危険コマンド拒否と安全フックのみ導入（モデルや権限は一切変更しない）
     - **[3] カスタム**: 項目ごとに個別に選択
3. **セットアップの実行（Execute）**:
   - 選択された内容に応じて、`scripts/setup.sh --target <TARGET> --preset <PRESET>` を実行する。
4. **完了報告と使い方の案内（Done）**:
   - `scripts/doctor.sh <TARGET>` で健全性を確認し、ユーザーに完了を報告する。
   - 「AIを賢く動かすための3つの鉄則」（いきなりコードを書かせず設計と質問から始める / テストで自己検証させる / 会話を長く引っ張らない）を添えて案内する。

---

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
scripts/doctor.sh                         # 前提ツールと各ターゲットのインストール状態を診断
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

## アンインストール

配布した設定を安全に削除したい場合は `uninstall.sh` を使用します。

```bash
scripts/uninstall.sh claude --dry-run     # 削除対象のファイル一覧を表示（削除はしない）
scripts/uninstall.sh claude               # 配布済みファイルを削除
```

`uninstall.sh` は `.harunon-slim.installed.json`（ledger）に記録された配布済みファイルのみを安全に削除し、未管理のファイルやユーザー独自のファイルは保持します。

## 環境診断（doctor）

現在の前提ツールの有無や、各ターゲットの配布状況・ドリフトを一括確認できます。

```bash
scripts/doctor.sh                         # 全ターゲットの診断
scripts/doctor.sh claude                  # 特定ターゲットのみ診断
```

## 設定ファイルの扱い

JSON（`claude/settings.json`・`opencode/opencode.json`・`pi/settings.json`）は、既存ファイルがあれば`install-manifest.json`の`settingsKeys`にあるキーだけをマージします。それ以外のローカル値は保持し、ファイルがなければ全体をコピーします。

TOML / YAML（`codex/config.toml`・`omp/config.yml`）は、配布先にないときだけコピーします。既にある場合は変更せず、`S config.toml (not merged: toml; ...)`と表示します。該当targetの`install-manifest.json`にある`settingsKeys`のキーを手で取り込んでください。

公開設定は安全hookと共通機能に必要なキーだけです。モデル、UI、個人用plugin / npm packageは指定しません。既存の値は保持し、新規環境ではruntimeの既定値を使います。

## 前提ツール

`install.sh`には`jq`と`rsync`、`validate.sh`にはさらに`node`と`python3`が必要です。hookもhook-runnerに`node`、policyの処理に`python3`を使います。`skill-creator`の検証スクリプトなど、一部のskillにはPyYAMLが必要です。

コマンド出力を圧縮するCLIのrtkは任意です。未導入の場合、`rtk-rewrite.sh`はコマンドを変更せずに通します。

worktreeはruntimeの標準機能かGitで作成できます。gwmは必須ではありません。共有checkoutの保護や破壊的操作の確認hookは残しています。

方針が明確な修正は main で実装・検証し、必要な調査・設計比較には pstack の skill を選びます。全体 orchestration は明示依頼時だけ使います。外部skill / native plugin は同梱・自動取得しないため、pstack を使う場合は[pstack の導入手順](https://github.com/michael-denyer/pstack-claude#install)に従って使用する runtime へ先に導入してください。Claude / Codex / Pi は native plugin、OpenCode / OMP は同リポジトリの全共有 skills を使います。Codex hook の trust は `/hooks` で行います。Issue tracker はプロジェクト設定と入力URLに従います。

## 境界

認証情報、OAuth token、providerのAPI keyは含めません。モデル定義に記載するのはcredentialの参照先だけです。
`scripts/validate.sh`は、credentialらしき文字列を検出すると失敗します。

## このリポジトリについて

このリポジトリはSSOTから生成した配布物です。ここで直接編集した内容は次の生成で上書きされるため、継続して使う変更はSSOT側へ取り込んでください。

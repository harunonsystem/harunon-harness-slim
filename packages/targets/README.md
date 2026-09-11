# Targets

各 AI ツール（Claude Code, Codex Desktop, OpenCode, pi, omp）への設定同期を管理するディレクトリ。

共通skillは`shared-agents` targetから`~/.agents/skills`へ1回だけ配布する。Codex / OpenCode / pi / ompはそれを参照し、runtime側へ共通skillを複製しない。

`portableFrontmatter` は共通仕様のフィールドだけを残す。Claude用の `disable-model-invocation` / `user-invocable` / `allowed-tools` などは共通配布先で同じ起動・権限制御を保証しない。制御が必要なskillは本文の適用範囲と `disabled-skills.json`・各targetの除外宣言も確認する。

pi（`@earendil-works/pi-coding-agent`）と omp（`@oh-my-pi/pi-coding-agent`）は別runtime・別schema。両者ともCore Workflowと同じnative gate adapterを配布する。omp は config（`~/.omp/agent/config.yml`）を settingsSync で管理キーのみ同期し、hooksはconfig.ymlのbash.patternsと配布されたhookRunner adapterで扱う。keybindingsはomp側で管理する。pi は config（`~/.pi/agent/settings.json`）の settingsSync に加え、hooks（claude-hooks-bridge 経由で Claude PreToolUse プロトコルを再現）と承認スクリプト（approve-push.sh）も配布する。keybindings は pi 側でネイティブ管理（pi は keybindings.json しか読まない）（詳細は各 `targets/*/config.json` の notes）。

## 設計原則

1. **SSOT は `packages/core/`**
   - ClaudeはcoreのCLAUDE.md、他runtimeは各targetのAGENTS.mdと共有fragmentsが指示の正本
   - hooks, rules, skills は共通ソース

2. **配布はファイルコピーで行う**
   - Claude Code: `bootstrap.sh` で SSOT → `~/.claude/` にコピー
   - Codex / OpenCode: `/sync-settings --push <target>` で AGENTS.md を expandIncludes 生成してコピー
   - ドリフトは `/sync-settings --check` で検出

3. **共通kernel/skillとruntime adapterを分ける**
   - shared-agents targetが共通skillを`~/.agents/skills`へ1回だけ配置する
   - 各runtime targetはnative adapterとconfigだけを各configDirへ配置する
   - ドリフトは定期的な `--check` で検出し、`--push` で修正

## 同期フロー

```
packages/core/ (SSOT)
    │
    ├─ --push shared-agents ──→ ~/.agents/skills/
    ├─ --push claude   ──→ ~/.claude/
    ├─ --push codex    ──→ ~/.codex/        (expandIncludes)
    ├─ --push opencode ──→ ~/.config/opencode/ (expandIncludes)
    ├─ --push opencode-launcher ──→ ~/.local/bin/opencode
    ├─ --push pi       ──→ ~/.pi/agent/     (content + settingsSync + hooks bridge)
    └─ --push omp      ──→ ~/.omp/agent/    (content + settingsSync)
```

### コマンド

| コマンド | 説明 |
| --- | --- |
| `/sync-settings --check [target]` | harness と各ターゲットの差分を表示 |
| `/sync-settings --push <target>` | harness → ターゲットに配布 |
| `/sync-settings --push all` | 全ターゲットに配布 |
| `/sync-settings --pull` | ローカル変更を harness に取り込み（差分提示） |
| `/sync-settings --update` | git fetch + harness-doctor + 差分方向の判定 |

### --push が配布するもの

| 対象 | Claude | Codex | OpenCode | pi | omp |
| --- | --- | --- | --- | --- | --- |
| 指示ファイル | CLAUDE.md（そのまま） | AGENTS.md（expandIncludes） | AGENTS.md（expandIncludes） | AGENTS.md（expandIncludes） | AGENTS.md（expandIncludes） |
| rules/ | コピー | コピー | コピー | コピー | コピー |
| skills/ | コピー | shared-agents targetを参照 | shared-agents targetを参照 | shared-agents targetを参照 | shared-agents targetを参照 |
| policy/・workflows/ | コピー | Codex plugin | コピー | コピー | コピー |
| hooks/ | shell hooks | Codex plugin | umbrella plugin + runtime/hook-runner/ + runtime/claude-hooks/（自己完結・fail-closed） | extensions/claude-hooks-bridge.ts + hook-runner/ + claude-hooks/（hook 選択は policy/hook-pipeline.json） | config.yml bash.patterns + extensions/omp-denial-reason.js + hook-runner/ + claude-hooks/ |
| config | settingsSync（hooks / sandbox / permissions.deny・ask / autoMode.hard_deny・soft_deny / fallbackModel / switchModelsOnFlag / env.HARNESS_RUNTIME） | settingsSync（config.toml の model / approval / features / agents / memories / tui 等の管理キー。local / extras は別管理） | settingsSync（opencode.json の permission/default_agent/instructions/skills のみ同期） | settingsSync（settings.json の管理キーを同期。ローカル蓄積キーは保持） | settingsSync（config.yml の modelRoles / hideThinkingBlock / enabledModels / permissions / skills 等の管理キー） |

## 構造

```
targets/
├── claude/           # Claude Code (~/.claude/)
│   └── config.json   # ターゲット設定
├── codex/            # Codex Desktop (~/.codex/)
│   └── config.json
├── opencode/         # OpenCode (~/.config/opencode/)
│   └── config.json
├── opencode-launcher/ # OpenCode startup env (~/.local/bin/opencode)
│   └── config.json
├── pi/               # pi coding agent (~/.pi/agent/)
│   ├── AGENTS.md
│   └── config.json   # hook の配線は packages/core/policy/hook-pipeline.json（hookRunner が実行時に読む）
├── omp/              # omp / oh-my-pi (~/.omp/agent/)
│   └── config.json
├── shared-agents/    # Shared Agent Skills (~/.agents/)
│   └── config.json
└── README.md
```

## ターゲット別の差分

| 項目 | Claude Code | Codex Desktop | OpenCode | pi | omp |
| --- | --- | --- | --- | --- | --- |
| 指示ファイル名 | CLAUDE.md | AGENTS.md | AGENTS.md | AGENTS.md | AGENTS.md |
| config ファイル | settings.json | config.toml | opencode.json | settings.json | config.yml |
| config dir | `~/.claude/` | `~/.codex/` | `~/.config/opencode/` | `~/.pi/agent/` | `~/.omp/agent/` |
| skills 配布方式 | コピー | shared-agents target を参照 | shared-agents target を参照 | shared-agents target を参照 | shared-agents targetを参照 |
| hooks 方式 | shell script (PreToolUse 等) | `harunon-core` Codex plugin | umbrella plugin (tool.execute.before) → hookRunner | extension (tool_call) → hookRunner が shell script を無改修実行 | config.yml bash.patterns + extension (tool_call) → hookRunner（deny 理由の説明） |
| Startup Self-Check | あり（model 検証） | なし | なし | なし | なし |
| Language セクション | system prompt で対応 | AGENTS.md に追加 | system prompt で対応 | AGENTS.md に追加 | AGENTS.md に追加 |

## 廃止予定のスキル

| スキル | 代替 |
| --- | --- |
| `/copy-skills-to-codex` | `/sync-settings --push codex` |

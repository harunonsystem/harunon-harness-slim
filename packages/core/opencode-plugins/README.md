# OpenCode runtime modules

OpenCode 固有の hook / custom tool 実装。これらを個別に auto-load せず、
`packages/runtimes/opencode/harunon.js` が決められた順序で合成する。
配布先では `plugins/harunon.js` だけが top-level plugin となり、実装群は
`runtime/harunon-opencode/` に置く。

## 構成

| module | 役割 |
| --- | --- |
| `harness-policy.js` | Bash / GitHub MCP の PR create・merge を正規化し、共通 Policy Kernel で認可 |
| `harness-workflow.js` | `harness_workflow` custom tool から `inspect` / `apply` / `authorize` と assignment 操作を呼ぶ |
| `claude-hooks-bridge.js` | bash の `tool.execute.before` を Claude の Bash / tool_input に写し、`../hook-runner/hook-runner.js`（hookRunner。`packages/core/hook-runner/` から `runtime/hook-runner/` へ配布）に渡す adapter。どの hook を流すか・wire protocol・required hook の fail-closed は hookRunner が `runtime/policy/hook-pipeline.json` から決め、`runtime/claude-hooks/*.sh` を無改修実行する。`~/.claude/hooks` には依存しない。ask は throw（deny）に落とす（確認 UI が無い） |
| `post-edit-checks.js` | write / edit 後の `tool.execute.after` で `../hook-runner/post-edit.js` を呼び、shellcheck / jq の指摘を tool result 末尾に追記する adapter（.md は fix-gfm-tables.js が担うため除外） |
| `tool-cwd.js` | 判定 cwd の SSOT: bash tool の `cwd` 引数 > `worktree`（`/` 除く）> `directory`。harness-policy / harness-workflow / claude-hooks-bridge が共有 |
| `fix-gfm-tables.js` / `scan-new-skills.js` | 編集後整形・skill 検出 |
| `model-providers.js` | OpenAI を含む provider 設定の統合 |

## 設計境界

- workflow state と action 判定は runtime-neutral な `policy/harnessctl.py` が唯一の真実。
- plugin は tool event を action と repo context に変換する adapter に留める。
- local review evidence は監査情報であり、merge の信頼境界は GitHub required check / branch protection。
- 読み込み順は umbrella plugin 側で固定し、複数 plugin の暗黙順序に依存しない。

公式 plugin contract: <https://opencode.ai/docs/plugins/>

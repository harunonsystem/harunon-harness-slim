# diagrams

`/archify` の spec（JSON）を置く。HTML は 700KB 級の生成物なので commit せず、必要なときに手元で生成する。図の修正は HTML ではなく spec に対して行う。

## harness.architecture.json

このリポジトリ自身の配布アーキテクチャ。SSOT 3 系統 → `targets/*/config.json` の宣言 → `Distribution` → 7 配布先、および配布された `policy/*.json` を配布先の `hook-runner.js` / `codex_hook.py` が実行時に読む関係を 1 枚にする。

```bash
A=~/.claude/skills/archify/bin/archify.mjs
node "$A" validate architecture docs/diagrams/harness.architecture.json --quality showcase --json
node "$A" deliver  architecture docs/diagrams/harness.architecture.json "$TMPDIR/harness-architecture.html" --quality showcase --json
node "$A" visual-check "$TMPDIR/harness-architecture.html" --json
```

`visual-check` は Chrome を起動するので Bash sandbox 内では失敗する（`Operation not permitted`）。sandbox を外して実行する。

内容が古くなる条件（更新のトリガー）:

- 配布ターゲットの増減 → components の右側 4 ボックス
- `policy/hook-pipeline.json` の hook 増減・`danger-rules.json` の rule 増減 → `policy` ノードの tag と 3 枚目のカード
- `packages/core/` のディレクトリ構成変更 → `core` ノードの tag

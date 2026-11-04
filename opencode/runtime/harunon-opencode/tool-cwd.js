// OpenCode の bash tool は `workdir` 引数（1.18 時点。`cwd` ではない）を持ち、
// セッションの project directory と別の場所（典型: gwm で切った独立 worktree）で
// コマンドを実行できる。
// plugin context の `worktree` / `directory` はセッション起点のままなので、
// そこだけを見ると承認フラグの KEY（repo root + branch + HEAD）と Core Workflow
// state の両方が親リポジトリで判定され、worktree で承認・開始した作業が
// 「承認したのに push が拒否される」「別タスクが占有中で PR が作れない」になる
// （2026-08-26 に業務リポジトリで実測）。
//
// tool 引数からの cwd 解決は共通 hook-runner/runtime-mapping.js の resolveCwd が持ち、
// ここはその base（セッション起点）だけを決める。
// non-git セッションで OpenCode が worktree に "/" を渡す防御はここに寄せる。

export function sessionBaseCwd({ directory, worktree } = {}) {
  return worktree && worktree !== "/" ? worktree : directory;
}

// OpenCode の bash tool は `cwd` 引数を持ち、セッションの project directory と
// 別の場所（典型: gwm で切った独立 worktree）でコマンドを実行できる。
// plugin context の `worktree` / `directory` はセッション起点のままなので、
// そこだけを見ると承認フラグの KEY（repo root + branch + HEAD）と Core Workflow
// state の両方が親リポジトリで判定され、worktree で承認・開始した作業が
// 「承認したのに push が拒否される」「別タスクが占有中で PR が作れない」になる
// （2026-08-26 に業務リポジトリで実測）。
//
// resolve 順は pi 版 claude-hooks-bridge.ts の resolveBaseCwd と同じ:
//   tool 引数の cwd（絶対ならそのまま、相対ならセッション base 基準）> セッション base。
// non-git セッションで OpenCode が worktree に "/" を渡す防御も 1 箇所に寄せる。

import { resolve } from "node:path";

export function sessionBaseCwd({ directory, worktree } = {}) {
  return worktree && worktree !== "/" ? worktree : directory;
}

export function resolveToolCwd(base, toolCwd) {
  if (typeof toolCwd !== "string" || toolCwd.trim() === "") return base;
  return resolve(base, toolCwd);
}

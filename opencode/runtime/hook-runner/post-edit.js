/**
 * write / edit 直後のファイル品質チェック（Claude Code の PostToolUse 相当）の共有 module。
 * 判定本体は claude-hooks/post-edit-checks.sh（runtime 中立 shell。.md → GFM 自動修正 /
 * .sh → shellcheck / .json,.jsonc → jq）で、ここは「どの拡張子なら shell を呼ぶか」と
 * 「spawn して stdout を findings として返す」だけを持つ。
 *
 * 指摘はモデルが自己修正するための追記なので advisory: script 欠落・spawn 失敗・timeout は
 * 黙って undefined（block しない）。adapter（pi-extensions / opencode-plugins）が持つのは
 * 「編集された path の取り出し方」と「tool result への追記の仕方」だけ。
 * SSOT: harunon-harness packages/core/hook-runner/
 */
import { join } from "node:path";
import { DEFAULT_HOOKS_DIR, runProcess } from "./hook-runner.js";

const CHECKS_SCRIPT = "post-edit-checks.sh";
const TIMEOUT_MS = 30_000;

export function checkKindFor(path) {
  if (typeof path !== "string") return undefined;
  if (path.endsWith(".md")) return "md";
  if (path.endsWith(".sh")) return "sh";
  if (path.endsWith(".json") || path.endsWith(".jsonc")) return "json";
  return undefined;
}

/**
 * @param {string} path 編集されたファイル
 * @param {{ hooksDir?: string, markdown?: boolean }} options
 *   markdown: false なら .md を扱わない（opencode は fix-gfm-tables.js が file.edited で担うため重ねない）
 * @returns {Promise<string|undefined>} 指摘テキスト（無ければ undefined）
 */
export async function postEditFindings(path, { hooksDir = DEFAULT_HOOKS_DIR, markdown = true } = {}) {
  const kind = checkKindFor(path);
  if (kind === undefined) return undefined;
  if (kind === "md" && !markdown) return undefined;
  const result = await runProcess("/bin/bash", [join(hooksDir, CHECKS_SCRIPT), path], {
    timeoutMs: TIMEOUT_MS,
  });
  const text = result.stdout.trim();
  return text ? text : undefined;
}

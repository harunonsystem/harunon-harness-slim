/**
 * pi / omp 向け: write / edit 後のファイル品質ゲート（Claude Code の PostToolUse 相当）の adapter。
 * 両 runtime の tool_result イベントは同名・同形（toolName "write"/"edit"、input.path、content、
 * isError、返り値 { content }。omp 18.2.0 の shared-events.ts / hooks/types.ts で互換を再確認済み）なので
 * 1 file で両方に配る。判定本体は ../hook-runner/post-edit.js → claude-hooks/post-edit-checks.sh。
 * ここが持つのは「編集 path の取り出し方（input.path）」と「content 末尾への追記」だけ。
 * SSOT: harunon-harness packages/core/pi-extensions/
 */
import { postEditFindings } from "../hook-runner/post-edit.js";

const EDIT_TOOLS = new Set(["write", "edit"]);

export function createToolResultHandler(options = {}) {
  return async (event) => {
    if (!EDIT_TOOLS.has(event.toolName)) return undefined;
    if (event.isError) return undefined;
    const path = event.input?.path;
    if (typeof path !== "string") return undefined;
    const findings = await postEditFindings(path, options);
    if (!findings) return undefined;
    return {
      content: [...event.content, { type: "text", text: `\n[post-edit-check]\n${findings}` }],
    };
  };
}

export default function postEditChecks(pi) {
  pi.on("tool_result", createToolResultHandler());
}

/**
 * pi / omp 向け: 編集後のファイル品質ゲート（Claude Code の PostToolUse 相当）の adapter。
 * 両 runtime の tool_result イベントは同形（toolName、input、content、isError、返り値 { content }）
 * なので 1 file で両方に配る。判定本体は ../hook-runner/post-edit.js → claude-hooks/post-edit-checks.sh。
 * 編集先の取り出しは ../hook-runner/runtime-mapping.js の editedPaths が単独で持つ
 * （write/edit の path、omp hashline の paths[]、apply_patch、exec_command 内の apply_patch heredoc）。
 * ここが持つのは「content 末尾への追記」だけ。
 * SSOT: harunon-harness packages/core/pi-extensions/
 */
import { postEditFindings } from "../hook-runner/post-edit.js";
import { editedPaths } from "../hook-runner/runtime-mapping.js";
import { japaneseOutputSessions, polishFile } from "../hook-runner/japanese-output.js";

export function createToolResultHandler(options = {}) {
  return async (event, ctx) => {
    if (event.isError) return undefined;
    const baseCwd = typeof ctx?.cwd === "string" && ctx.cwd ? ctx.cwd : process.cwd();
    const reports = [];
    for (const path of editedPaths(event.toolName, event.input, baseCwd)) {
      const policy = japaneseOutputSessions.get(ctx?.sessionManager?.getSessionId());
      if (policy && !policy.bypass && ["write", "edit", "apply_patch"].includes(event.toolName)) {
        try {
          const outcome = await polishFile(path, policy.polish);
          if (outcome === "changed") reports.push(`\n[japanese-output] ${path}: 日本語を推敲しました。保存内容を読み直し、その内容で検証してください。`);
          if (outcome === "concurrent-edit") reports.push(`\n[japanese-output] ${path}: 別の編集を検出したため、推敲結果を保存しませんでした。`);
        } catch {
          reports.push(`\n[japanese-output] ${path}: 推敲結果を保存できませんでした。ファイルの状態を確認してから検証してください。`);
        }
      }
      const findings = await postEditFindings(path, options);
      if (findings) reports.push(`\n[post-edit-check] ${path}\n${findings}`);
    }
    if (reports.length === 0) return undefined;
    return {
      content: [...event.content, ...reports.map((text) => ({ type: "text", text }))],
    };
  };
}

export default function postEditChecks(pi) {
  pi.on("tool_result", createToolResultHandler());
}

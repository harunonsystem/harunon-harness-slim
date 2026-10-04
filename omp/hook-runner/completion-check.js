/**
 * ターン終了時の完了申告を v2 kernel と照合する（pi / omp 共通）。判定は Claude / Codex と同じ
 * require-evidence-for-completion.py（--kernel-only）に任せ、差し戻す理由だけを返す。
 * SSOT: harunon-harness packages/core/hook-runner/
 */
import { fileURLToPath } from "node:url";
import { runProcess } from "./hook-runner.js";

const HOOK = fileURLToPath(
  new URL("../claude-hooks/require-evidence-for-completion.py", import.meta.url),
);

/** 文字列、または pi / omp の AgentMessage（content に text part を持つ）から本文を取り出す。 */
export function messageText(message) {
  if (typeof message === "string") return message;
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

/** 差し戻すなら理由の文字列、通すなら undefined。 */
export async function completionSendBack({ cwd, message, stopHookActive = false }, run = runProcess) {
  const result = await run("python3", [HOOK, "--kernel-only"], {
    stdin: JSON.stringify({
      cwd: typeof cwd === "string" && cwd ? cwd : process.cwd(),
      stop_hook_active: stopHookActive === true,
      last_assistant_message: messageText(message),
    }),
  });
  // hook は判定を stdout に出して常に 0 で終わる。それ以外（配布漏れ等）は照合できていない。
  if (result.code !== 0) return `完了照合 hook が失敗しました: ${result.stderr.trim() || result.code}`;
  if (!result.stdout.trim()) return undefined;
  const decision = JSON.parse(result.stdout);
  return decision?.decision === "block" ? decision.reason : undefined;
}

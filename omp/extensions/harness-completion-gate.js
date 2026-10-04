/**
 * omp の session_stop で完了申告を v2 kernel と照合し、未完了なら 1 回だけ差し戻す。
 * 再停止は omp の stop_hook_active で通す。
 * SSOT: harunon-harness packages/core/omp-extensions/
 */
import { completionSendBack } from "../hook-runner/completion-check.js";

export function createCompletionGate(run) {
  return async (event, ctx) => {
    const reason = await completionSendBack(
      {
        cwd: ctx?.cwd,
        message: event?.last_assistant_message,
        stopHookActive: event?.stop_hook_active,
      },
      run,
    );
    return reason === undefined ? undefined : { decision: "block", reason };
  };
}

export default function harnessCompletionGate(pi) {
  pi.on("session_stop", createCompletionGate());
}

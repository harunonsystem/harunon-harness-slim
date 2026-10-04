/**
 * pi の agent_before_settle で完了申告を v2 kernel と照合し、未完了なら理由を注入して
 * 1 回だけ続行させる。pi には stop_hook_active がないので、差し戻しはユーザー入力ごとに 1 回まで。
 * SSOT: harunon-harness packages/core/pi-extensions/
 */
import { completionSendBack } from "../hook-runner/completion-check.js";

function lastAssistantMessage(messages) {
  return [...(messages ?? [])].reverse().find((entry) => entry?.role === "assistant");
}

export function createCompletionGate(run) {
  let sentBack = false;
  return {
    onInput() {
      sentBack = false;
      return { action: "continue" };
    },
    async onBeforeSettle(event, ctx) {
      // 他の extension が続行を決めた、正常終了でない場合は照合しない。context.canContinue は
      // 注入前（最後が assistant）なので常に false。注入後の続行可否は pi 本体が再判定する。
      if (event?.continue || event?.outcome !== "completed") {
        return undefined;
      }
      const reason = await completionSendBack(
        { cwd: ctx?.cwd, message: lastAssistantMessage(event.context?.contextMessages), stopHookActive: sentBack },
        run,
      );
      if (reason === undefined) return undefined;
      sentBack = true;
      return {
        continue: true,
        entries: [{ type: "custom_message", customType: "harness-completion-gate", content: reason, display: true }],
      };
    },
  };
}

export default function harnessCompletionGate(pi) {
  const gate = createCompletionGate();
  pi.on("input", gate.onInput);
  pi.on("agent_before_settle", gate.onBeforeSettle);
}

/**
 * omp の tool_call を hookRunner（../hook-runner/hook-runner.js）へ渡す adapter。
 *
 * omp の危険コマンド判定は config.yml の bash.patterns（danger-rules.json 由来の glob）が
 * 担うが、glob deny はメッセージを運べず、エージェントには「denied」しか見えない
 * （approve-push.sh を実行する / SSOT を直す、といった次の行動が学べない）。
 * この extension は tool_call ごとに hookRunner を HARNESS_RUNTIME=omp で走らせ、
 * deny のとき hook の理由（rule の message = 次の行動）で block する。
 * omp に配線される hook は policy/hook-pipeline.json の runtimes が決める
 * （required なので配布漏れは hookRunner が deny に倒す）。
 *
 * decision の写し方（ask は ctx.ui.confirm、UI 無しなら block）は pi bridge と共通の
 * settleDecision が持つ。updatedInput は ToolCallEventResult.input で書き戻す（rtk-rewrite）。
 * hashline の複数ファイル edit は path を持たず paths[] だけを渡すので、file ごとに
 * file_path を付けて Edit hooks（block-edit-on-main）に流す。
 * SSOT: harunon-harness packages/core/omp-extensions/
 */
import { createHookRunner } from "../hook-runner/hook-runner.js";
import {
  hookInputsPerFile,
  normalizeToolCall,
  restoreToolInput,
  settleDecision,
} from "../hook-runner/runtime-mapping.js";

export function createDenialReasonHandler(runner) {
  return async (event, ctx) => {
    const baseCwd = typeof ctx?.cwd === "string" && ctx.cwd ? ctx.cwd : process.cwd();
    const normalized = normalizeToolCall("omp", event?.toolName, event?.input ?? {}, baseCwd);
    if (!normalized) return undefined;
    const inputs = hookInputsPerFile(normalized, event.toolName, event.input);
    let result;
    for (const input of inputs) {
      result = await runner.preToolUse(normalized.toolName, input, normalized.cwd);
      const blocked = await settleDecision(result, ctx);
      if (blocked) return blocked;
    }

    // rewrite 系 hook（rtk-rewrite）が updatedInput を返したときだけ実行入力を
    // 書き戻す。runner は入力を必ずコピーするので参照ではなく内容で比較する
    // （updatedInput が新しいキーを足せば stringify でも差が出る）。書き戻すのは
    // omp 側のフィールド形（exec_command は cmd）に戻したもの。file ごとに分けた
    // 検査用の入力（file_path 付き）は書き戻さない。
    if (inputs.length === 1 && JSON.stringify(result.finalInput) !== JSON.stringify(normalized.input)) {
      return { input: restoreToolInput("omp", event.toolName, result.finalInput) };
    }
    return undefined;
  };
}

export default function ompDenialReason(pi) {
  pi.on("tool_call", createDenialReasonHandler(createHookRunner({ runtime: "omp" })));
}

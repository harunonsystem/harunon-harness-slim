/**
 * omp の bash deny に理由を付ける adapter。
 *
 * omp の危険コマンド判定は config.yml の bash.patterns（danger-rules.json 由来の glob）が
 * 担うが、glob deny はメッセージを運べず、エージェントには「denied」しか見えない
 * （approve-push.sh を実行する / SSOT を直す、といった次の行動が学べない）。
 * この extension は bash の tool_call ごとに hookRunner（../hook-runner/hook-runner.js）を
 * HARNESS_RUNTIME=omp で走らせ、deny のとき hook の理由（rule の message = 次の行動）で
 * block する。allow なら何もしない（deny の主体は引き続き bash.patterns。ここは説明と
 * 第二防衛線）。omp に配線される hook は policy/hook-pipeline.json の runtimes が決める
 * （現状 block-dangerous-in-bash のみ。required なので配布漏れは hookRunner が deny に倒す）。
 *
 * omp 固有の差（scripts/tests/fixtures/hook-protocol.json に divergence として宣言）:
 * 確認 UI を持たないため ask は block に倒し、updatedInput は書き戻さない（rtk-rewrite は
 * omp に配線しない）。
 * SSOT: harunon-harness packages/core/omp-extensions/
 */
import { resolve as resolvePath } from "node:path";
import { createHookRunner } from "../hook-runner/hook-runner.js";

export function createDenialReasonHandler(runner) {
  return async (event, ctx) => {
    if (event?.toolName !== "bash") return undefined;
    const command = event.input?.command;
    if (typeof command !== "string") return undefined;
    const inputCwd = typeof event.input.cwd === "string" ? event.input.cwd : undefined;
    // ctx.cwd が無い呼び出しでも throw で handler を reject させない（reject 時の扱いは omp 側に委ねない）
    const baseCwd = typeof ctx?.cwd === "string" && ctx.cwd ? ctx.cwd : process.cwd();
    const cwd = inputCwd ? resolvePath(baseCwd, inputCwd) : baseCwd;
    const result = await runner.preToolUse("Bash", { command }, cwd);
    if (result.decision === "allow") return undefined;
    return { block: true, reason: result.reason || "harness guard hook が理由なしで deny しました" };
  };
}

export default function ompDenialReason(pi) {
  pi.on("tool_call", createDenialReasonHandler(createHookRunner({ runtime: "omp" })));
}

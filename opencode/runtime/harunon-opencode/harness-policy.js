import { AMBIGUOUS_PR_ACTION } from "../policy/pr-action.js";
import { authorize, classifyToolCall, gateToolCall } from "../policy/publication-gate.js";
import { resolveToolCwd, sessionBaseCwd } from "./tool-cwd.js";

const SHELL_TOOLS = new Set(["bash", "exec_command", "interactive_shell"]);

function commandFromTool(output) {
  const args = output?.args;
  if (typeof args?.command === "string") return args.command;
  if (typeof args?.cmd === "string") return args.cmd;
  return undefined;
}

const toolNameOf = (input) => input?.tool ?? input?.name ?? input?.toolName ?? "";

// shell 以外の tool の引数に入った command 文字列は実行されないので分類しない
function shellCommand(input, output) {
  return SHELL_TOOLS.has(toolNameOf(input)) ? commandFromTool(output) : undefined;
}

export function actionFromTool(input, output) {
  const action = classifyToolCall(toolNameOf(input), shellCommand(input, output));
  return action === AMBIGUOUS_PR_ACTION ? undefined : action;
}

export function createHarnessPolicy(run = authorize) {
  // directory は project root を指すため、独立 worktree では別タスクの state を
  // 参照してしまう。worktree を優先し、さらに bash tool の cwd 引数（セッションと
  // 別の worktree でコマンドを実行する形）があればそれを base にする
  // （harness-workflow.js と同じ解決。tool-cwd.js が SSOT）。
  return async ({ directory, worktree }) => ({
    "tool.execute.before": async (input, output) => {
      const cwd = resolveToolCwd(
        sessionBaseCwd({ directory, worktree }),
        output?.args?.workdir ?? output?.args?.cwd,
      );
      const verdict = await gateToolCall(
        { toolName: toolNameOf(input), command: shellCommand(input, output), cwd },
        run,
      );
      if (verdict && !verdict.allowed) throw new Error(verdict.reason);
    },
  });
}

export const HarnessPolicy = createHarnessPolicy();

/**
 * PR 公開操作（作成・merge）を Core Workflow kernel（harnessctl.py authorize）に通す共有 module。
 *
 * 分類（shell command と GitHub MCP tool 名）と kernel 呼び出しをここに 1 つだけ置き、
 * hook（hooks/harness-publication-gate.sh）・pi / omp / opencode の extension・codex adapter は
 * 自分の tool call から toolName / command / cwd を取り出して gateToolCall に渡すだけにする。
 * policy/ は全 runtime に丸ごと配られるので、hook-runner/ に依存しない（claude には無い）。
 */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { AMBIGUOUS_PR_ACTION, classifyPrCommand } from "./pr-action.js";

const KERNEL = fileURLToPath(new URL("./harnessctl.py", import.meta.url));
const KERNEL_TIMEOUT_MS = 60_000;

/** GitHub MCP の tool 名、または shell command から PR action を返す。 */
export function classifyToolCall(toolName, command) {
  const name = String(toolName ?? "");
  if (/github.*create.*pull.*request/i.test(name)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(name)) return "pr.merge";
  return classifyPrCommand(command);
}

/** kernel の authorize を 1 回呼ぶ。code 0 が許可。 */
export function authorize(action, cwd, command, kernel = KERNEL) {
  return new Promise((done) => {
    let output = "";
    let child;
    try {
      child = spawn("python3", [kernel, "authorize"], { cwd, timeout: KERNEL_TIMEOUT_MS });
    } catch (error) {
      done({ code: 1, reason: `harnessctl を起動できません: ${error.message}` });
      return;
    }
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", (error) => done({ code: 1, reason: `harnessctl を起動できません: ${error.message}` }));
    child.on("close", (code) => done({ code: code ?? 1, reason: output.trim() || `harnessctl exited ${code}` }));
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify({ repo: cwd, action, command }));
  });
}

/**
 * 公開操作でなければ undefined。公開操作なら kernel の判定を { allowed, reason } で返す。
 * 1 コマンドに複数の PR action がある場合は、どれか 1 つだけを承認しないよう拒否する。
 */
export async function gateToolCall({ toolName, command, cwd }, run = authorize) {
  const action = classifyToolCall(toolName, command);
  if (action === undefined) return undefined;
  if (action === AMBIGUOUS_PR_ACTION) {
    return {
      allowed: false,
      reason: "Core Workflow policy blocked ambiguous PR actions: command contains multiple PR actions",
    };
  }
  const result = await run(action, cwd, command);
  return result.code === 0
    ? { allowed: true, reason: "" }
    : { allowed: false, reason: `Core Workflow policy blocked ${action}: ${result.reason}` };
}

/**
 * Claude PreToolUse hook（stdin JSON → exit 2 + stderr で deny）として判定し、exit code を返す。
 * hooks/harness-publication-gate.sh が import して呼ぶ。entry 判定を持たないのは、判定が
 * 外れたとき何もせず exit 0（= 素通り）になる経路を作らないため。
 */
export async function runAsHook(stdin = readFileSync(0, "utf8")) {
  let event;
  try {
    event = JSON.parse(stdin);
  } catch {
    process.stderr.write("Invalid publication hook input\n");
    return 2;
  }
  const verdict = await gateToolCall({
    toolName: event?.tool_name,
    command: event?.tool_input?.command,
    cwd: typeof event?.cwd === "string" && event.cwd ? event.cwd : process.cwd(),
  });
  if (verdict && !verdict.allowed) {
    process.stderr.write(`${verdict.reason}\n`);
    return 2;
  }
  return 0;
}

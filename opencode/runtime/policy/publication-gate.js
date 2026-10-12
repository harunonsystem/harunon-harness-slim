/**
 * PR 公開操作（作成・merge）を Core Workflow kernel（harnessctl.py authorize）に通す共有 module。
 *
 * 分類（shell command と GitHub MCP tool 名）と kernel 呼び出しをここに 1 つだけ置き、
 * hook（hooks/harness-publication-gate.sh）・pi / omp / opencode の extension・codex adapter は
 * 自分の tool call から toolName / command / cwd を取り出して gateToolCall に渡すだけにする。
 * policy/ は全 runtime に丸ごと配られるので、hook-runner/ に依存しない（claude には無い）。
 */
import { spawn } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { AMBIGUOUS_PR_ACTION, classifyPrCommand, publicationInput } from "./pr-action.js";

const KERNEL = fileURLToPath(new URL("./harnessctl.py", import.meta.url));
const KERNEL_TIMEOUT_MS = 60_000;

/** GitHub MCP の tool 名、または shell command から PR action を返す。 */
export function classifyToolCall(toolName, command, input) {
  const name = String(toolName ?? "");
  if (/github.*create.*pull.*request/i.test(name)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(name)) return "pr.merge";
  if (/github.*update.*pull.*request/i.test(name) && input && Object.hasOwn(input, "body")) return "pr.update-body";
  return classifyPrCommand(command);
}

/** kernel の authorize を 1 回呼ぶ。code 0 が許可。 */
export function authorize(action, cwd, command, publication, kernel = KERNEL) {
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
    child.stdin.end(JSON.stringify({ repo: cwd, action, command, publication }));
  });
}

/**
 * 公開操作でなければ undefined。公開操作なら kernel の判定を { allowed, reason } で返す。
 * 1 コマンドに複数の PR action がある場合は、どれか 1 つだけを承認しないよう拒否する。
 */
export async function gateToolCall({ toolName, command, cwd, input }, run = authorize) {
  const action = classifyToolCall(toolName, command, input);
  if (action === undefined) return undefined;
  if (action === AMBIGUOUS_PR_ACTION) {
    return {
      allowed: false,
      reason: "Core Workflow policy blocked ambiguous PR actions: command contains multiple PR actions",
    };
  }
  let publication;
  if (action === "pr.create" || action === "pr.update-body") {
    if (typeof command === "string") {
      publication = publicationInput(command);
      if (publication.bodyFile !== undefined) {
        try {
          const path = resolve(cwd, publication.bodyFile);
          if (!statSync(path).isFile()) throw new Error("regular final body file required");
          publication.body = readFileSync(path, "utf8");
        }
        catch { publication.bodyError = "Final body file is missing or not readable"; }
        delete publication.bodyFile;
      }
    } else {
      const repository = input?.repository_full_name ?? input?.repo_full_name ?? input?.repository ?? (input?.owner && input?.repo ? `${input.owner}/${input.repo}` : undefined);
      const headBranch = input?.head_branch ?? input?.head;
      publication = { body: input?.body, repository, headBranch, number: input?.pr_number ?? input?.pull_number ?? input?.pull_request_number ?? input?.number,
        ...(input?.head_repo ? { headRepository: input.head_repo } : {}) };
      if (!repository || (action === "pr.create" && !headBranch)) {
        publication.body = undefined;
        publication.bodyError = "Structured publication requires explicit repository and create head branch";
      }
    }
  }
  const result = publication === undefined ? await run(action, cwd, command) : await run(action, cwd, command, publication);
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
    input: event?.tool_input,
    cwd: typeof event?.cwd === "string" && event.cwd ? event.cwd : process.cwd(),
  });
  if (verdict && !verdict.allowed) {
    process.stderr.write(`${verdict.reason}\n`);
    return 2;
  }
  return 0;
}

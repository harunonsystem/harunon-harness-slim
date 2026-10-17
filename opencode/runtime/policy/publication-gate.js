/**
 * PR 公開操作（作成・merge）を Core Workflow kernel（harnessctl.py authorize）に通す共有 module。
 *
 * 分類（shell command と GitHub MCP tool 名）と kernel 呼び出しをここに 1 つだけ置き、
 * hook（hooks/harness-publication-gate.sh）・pi / omp / opencode の extension・codex adapter は
 * 自分の tool call から toolName / command / cwd を取り出して gateToolCall に渡すだけにする。
 * policy/ は全 runtime に丸ごと配られるので、hook-runner/ に依存しない（claude には無い）。
 */
import { spawn } from "node:child_process";
import { closeSync, constants, fstatSync, openSync, readFileSync } from "node:fs";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { AMBIGUOUS_PR_ACTION, classifyPrCommand, publicationInput } from "./pr-action.js";

const KERNEL = fileURLToPath(new URL("./harnessctl.py", import.meta.url));
const KERNEL_TIMEOUT_MS = 60_000;
const OUTPUT_CAP = 1024 * 1024;

/** GitHub MCP の tool 名、または shell command から PR action を返す。 */
export function classifyToolCall(toolName, command, input) {
  const name = String(toolName ?? "");
  if (/github.*create.*pull.*request/i.test(name)) return "pr.create";
  if (/github.*merge.*pull.*request/i.test(name)) return "pr.merge";
  if (/github.*update.*pull.*request/i.test(name) && input && Object.hasOwn(input, "body")) return "pr.update-body";
  return classifyPrCommand(command);
}

/**
 * kernel の authorize を 1 回呼ぶ。code 0 が許可。
 * 出力は合計 1 MiB で打ち切り、timeout では process group ごと殺す
 * （hook-runner.ts の runProcess と同形。policy/ は hook-runner に依存できないため移植）。
 */
export function authorize(action, cwd, command, publication, kernel = KERNEL) {
  return new Promise((done) => {
    let child;
    try {
      child = spawn("python3", [kernel, "authorize"], { cwd, detached: process.platform !== "win32" });
    } catch (error) {
      done({ code: 1, reason: `harnessctl を起動できません: ${error.message}` });
      return;
    }
    const decoder = new StringDecoder("utf8");
    let output = "";
    let captured = 0;
    let settled = false;
    const kill = () => {
      if (!child.pid) return;
      try {
        if (process.platform === "win32") child.kill("SIGKILL");
        else process.kill(-child.pid, "SIGKILL");
      } catch {
        try { child.kill("SIGKILL"); } catch { /* already exited */ }
      }
    };
    const finish = (code, diagnostic = "") => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      output += decoder.end();
      if (diagnostic) {
        if (output && !output.endsWith("\n")) output += "\n";
        output += diagnostic;
      }
      done({ code, reason: output.trim() || `harnessctl exited ${code}` });
    };
    const timer = setTimeout(() => {
      kill();
      finish(1, `harnessctl timed out after ${KERNEL_TIMEOUT_MS}ms`);
    }, KERNEL_TIMEOUT_MS);
    const capture = (chunk) => {
      if (settled) return;
      const remaining = OUTPUT_CAP - captured;
      const accepted = chunk.subarray(0, Math.max(remaining, 0));
      captured += accepted.length;
      output += decoder.write(accepted);
      if (accepted.length < chunk.length) {
        kill();
        finish(1, `harnessctl output exceeded ${OUTPUT_CAP} bytes`);
      }
    };
    child.stdout.on("data", capture);
    child.stderr.on("data", capture);
    child.on("error", (error) => finish(1, `harnessctl を起動できません: ${error.message}`));
    child.on("close", (code) => finish(code ?? 1));
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
        let fd;
        try {
          const path = resolve(cwd, publication.bodyFile);
          // FIFO は書き手が来るまで open が戻らないので、非ブロッキングで開いてから種類を確かめる。
          fd = openSync(path, constants.O_RDONLY | constants.O_NONBLOCK);
          const info = fstatSync(fd);
          if (!info.isFile() || info.size > 1024 * 1024) throw new Error("body file size or type rejected");
          publication.body = readFileSync(fd, "utf8");
        }
        catch { publication.bodyError = "Final body file is missing or not readable"; }
        finally { if (fd !== undefined) closeSync(fd); }
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

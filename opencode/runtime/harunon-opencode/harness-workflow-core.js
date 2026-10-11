import { fileURLToPath } from "node:url";
import { runProcess } from "../hook-runner/hook-runner.js";

const KERNEL = fileURLToPath(new URL("../policy/harnessctl.py", import.meta.url));

export async function invokeKernel(command, request, cwd) {
  const result = await runProcess("python3", [KERNEL, command], {
    cwd,
    stdin: JSON.stringify({ repo: cwd, ...request }),
    timeoutMs: request.operation === "verify" ? 2_147_483_647 : undefined,
  });
  const output = result.stdout.trim() || result.stderr.trim();
  if (result.code === 0) return output;
  throw new Error(output || `harnessctl exited ${result.code}`);
}

export function compileWorkflowRequest(args) {
  const operationArguments = { ...args };
  delete operationArguments.operation;
  delete operationArguments.cwd;
  return { operation: args.operation, arguments: operationArguments };
}

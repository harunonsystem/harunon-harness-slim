// Generated from packages/hook-engine/src/hook-runner.ts. Do not edit.

// src/hook-runner.ts
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
var HERE = dirname(fileURLToPath(import.meta.url));
var DEFAULT_HOOKS_DIR = join(HERE, "..", "claude-hooks");
var DEFAULT_TABLE_PATH = join(HERE, "..", "policy", "hook-pipeline.json");
var DEFAULT_TIMEOUT_MS = 6e4;
var DEFAULT_MAX_OUTPUT_BYTES = 1048576;
function message(error) {
  return error instanceof Error ? error.message : String(error);
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function expect(value, guard, path, type) {
  if (!guard(value)) throw new Error(`${path}: expected ${type}`);
  return value;
}
var isString = (value) => typeof value === "string";
var isBoolean = (value) => typeof value === "boolean";
var isFiniteNumber = (value) => typeof value === "number" && Number.isFinite(value);
var isStringArray = (value) => Array.isArray(value) && value.every(isString);
var isHookFile = (value) => isString(value) && /^[\w.-]+\.sh$/.test(value);
var isPermission = (value) => value === "allow" || value === "deny" || value === "ask";
function optional(record, key, guard, path, type) {
  return record[key] === void 0 ? {} : { [key]: expect(record[key], guard, `${path}.${key}`, type) };
}
function parseHook(value, path) {
  const hook = expect(value, isRecord, path, "object");
  const when = hook.when === void 0 ? void 0 : expect(hook.when, isRecord, `${path}.when`, "object");
  return {
    id: expect(hook.id, isString, `${path}.id`, "string"),
    file: expect(hook.file, isHookFile, `${path}.file`, "*.sh file name"),
    order: expect(hook.order, isFiniteNumber, `${path}.order`, "finite number"),
    stage: expect(hook.stage, isString, `${path}.stage`, "string"),
    runtimes: expect(hook.runtimes, isStringArray, `${path}.runtimes`, "string[]"),
    ...optional(hook, "event", isString, path, "string"),
    ...optional(hook, "required", isBoolean, path, "boolean"),
    ...when && { when: {
      ...optional(when, "tools", isStringArray, `${path}.when`, "string[]"),
      ...optional(when, "commandEre", isString, `${path}.when`, "string")
    } }
  };
}
function parsePipeline(value) {
  const table = expect(value, isRecord, "$", "object");
  if (table.version !== 1) throw new Error("$.version: expected 1");
  const runtimes = expect(table.runtimes, isRecord, "$.runtimes", "object");
  const hooks = expect(table.hooks, Array.isArray, "$.hooks", "array");
  return {
    version: 1,
    stages: expect(table.stages, isStringArray, "$.stages", "string[]"),
    runtimes: Object.fromEntries(Object.entries(runtimes).map(([name, runtime]) => {
      const path = `$.runtimes.${name}`;
      const { executionModel } = expect(runtime, isRecord, path, "object");
      return [name, { executionModel: expect(executionModel, isString, `${path}.executionModel`, "string") }];
    })),
    hooks: hooks.map((hook, index) => parseHook(hook, `$.hooks[${index}]`))
  };
}
function parseHookOutput(value) {
  const output = expect(value, isRecord, "$", "object");
  if (output.hookSpecificOutput === void 0) return void 0;
  const specific = expect(output.hookSpecificOutput, isRecord, "$.hookSpecificOutput", "object");
  const path = "$.hookSpecificOutput";
  return {
    ...optional(specific, "permissionDecision", isPermission, path, "allow | deny | ask"),
    ...optional(specific, "permissionDecisionReason", isString, path, "string"),
    ...optional(specific, "updatedInput", isRecord, path, "object")
  };
}
function normalizeShellCommand(command) {
  const deployed = join(DEFAULT_HOOKS_DIR, "lib", "command-normalize.sh");
  const source = existsSync(deployed) ? deployed : join(HERE, "..", "hooks", "lib", "command-normalize.sh");
  const result = spawnSync("/bin/bash", ["-c", 'source "$1" && normalize_command "$(cat)"', "normalize", source], {
    input: command,
    env: { ...process.env, NORMALIZE_KEEP_SUDO: "1" },
    encoding: "utf8",
    timeout: 5e3,
    maxBuffer: DEFAULT_MAX_OUTPUT_BYTES
  });
  if (result.error || result.status !== 0 || command && !result.stdout) {
    throw new Error("shell command normalization unavailable");
  }
  return result.stdout;
}
function loadPipeline(tablePath = DEFAULT_TABLE_PATH) {
  try {
    const raw = JSON.parse(readFileSync(tablePath, "utf8"));
    const table = parsePipeline(raw);
    for (const hook of table.hooks) {
      if (hook.when?.commandEre) new RegExp(hook.when.commandEre);
    }
    return table;
  } catch (error) {
    throw new Error(`hook-runner: hook-pipeline.json \u3092\u8AAD\u307F\u8FBC\u3081\u307E\u305B\u3093\uFF08${tablePath}\uFF09: ${message(error)}`);
  }
}
function selectHooks(table, runtime, toolName) {
  return table.hooks.filter(
    (hook) => hook.runtimes.includes(runtime) && (hook.event ?? "PreToolUse") === "PreToolUse" && (hook.when?.tools ?? []).includes(toolName)
  ).sort((a, b) => a.order - b.order);
}
function commandMatches(hook, input) {
  const ere = hook.when?.commandEre;
  return !ere || new RegExp(ere).test(typeof input.command === "string" ? input.command : "");
}
function hookEnv(runtime) {
  const entries = (process.env.PATH ?? "").split(":").filter(Boolean);
  for (const entry of ["/bin", "/usr/bin"]) {
    if (!entries.includes(entry)) entries.push(entry);
  }
  return { ...process.env, PATH: entries.join(":"), HARNESS_RUNTIME: runtime };
}
function killProcessTree(child) {
  if (!child.pid) return;
  try {
    if (process.platform === "win32") child.kill("SIGKILL");
    else process.kill(-child.pid, "SIGKILL");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return;
    try {
      child.kill("SIGKILL");
    } catch {
    }
  }
}
function runProcess(file, args, {
  cwd,
  env,
  stdin,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  maxOutputBytes = DEFAULT_MAX_OUTPUT_BYTES,
  signal
} = {}) {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve({ code: 1, stdout: "", stderr: "hook interrupted" });
      return;
    }
    let child;
    try {
      child = spawn(file, args, {
        cwd,
        env,
        detached: process.platform !== "win32",
        stdio: [stdin === void 0 ? "ignore" : "pipe", "pipe", "pipe"]
      });
    } catch (error) {
      resolve({ code: 1, stdout: "", stderr: `spawn failed (cwd=${cwd}): ${message(error)}` });
      return;
    }
    const outputLimit = Number.isFinite(maxOutputBytes) && maxOutputBytes >= 0 ? Math.floor(maxOutputBytes) : DEFAULT_MAX_OUTPUT_BYTES;
    const stdoutDecoder = new StringDecoder("utf8");
    const stderrDecoder = new StringDecoder("utf8");
    let stdout = "";
    let stderr = "";
    let capturedBytes = 0;
    let settled = false;
    const finish = (code, diagnostic = "", discardStdout = false) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      stdout += stdoutDecoder.end();
      stderr += stderrDecoder.end();
      if (diagnostic) {
        if (stderr && !stderr.endsWith("\n")) stderr += "\n";
        stderr += diagnostic;
      }
      child.stdout?.destroy();
      child.stderr?.destroy();
      child.stdin?.destroy();
      resolve({ code, stdout: discardStdout ? "" : stdout, stderr });
    };
    const abort = (diagnostic) => {
      killProcessTree(child);
      finish(1, diagnostic, true);
    };
    const onAbort = () => abort("hook interrupted");
    const timer = setTimeout(() => abort(`hook timed out after ${timeoutMs}ms`), timeoutMs);
    signal?.addEventListener("abort", onAbort, { once: true });
    const capture = (stream, chunk) => {
      if (settled) return;
      const remaining = outputLimit - capturedBytes;
      const accepted = chunk.subarray(0, Math.max(remaining, 0));
      capturedBytes += accepted.length;
      if (stream === "stdout") stdout += stdoutDecoder.write(accepted);
      else stderr += stderrDecoder.write(accepted);
      if (accepted.length < chunk.length) abort(`hook output exceeded ${outputLimit} bytes`);
    };
    child.stdout?.on("data", (chunk) => capture("stdout", chunk));
    child.stderr?.on("data", (chunk) => capture("stderr", chunk));
    child.on("close", (code) => finish(code));
    child.on("error", (error) => finish(1, `spawn failed (cwd=${cwd}): ${message(error)}`, true));
    if (stdin !== void 0 && child.stdin) {
      child.stdin.on("error", () => {
      });
      child.stdin.end(stdin);
    }
  });
}
function deny(reason, finalInput, warnings) {
  return { decision: "deny", reason, finalInput, warnings };
}
async function evaluate(table, runtime, hooksDir, timeoutMs, toolName, toolInput, cwd, signal) {
  if (!isRecord(toolInput)) return deny("tool input is invalid", {}, []);
  let input = { ...toolInput };
  const selected = selectHooks(table, runtime, toolName);
  const warnings = [];
  const askReasons = [];
  let frozenCommand;
  const missing = selected.filter((hook) => hook.required && !existsSync(join(hooksDir, hook.file)));
  if (missing.length > 0) {
    return deny(
      `required security hook missing: ${missing.map((hook) => hook.file).join(", ")} (${hooksDir}) \u2014 scripts/install.sh ${runtime}\uFF08slim\uFF09\u307E\u305F\u306F\u914D\u5E03\u5143 repo \u3067 scripts/bootstrap.sh --targets ${runtime} \u3092\u5B9F\u884C\u3057\u3066 hooks \u3092\u518D\u914D\u5E03\u3057\u3066\u304F\u3060\u3055\u3044`,
      input,
      warnings
    );
  }
  for (const hook of selected) {
    const path = join(hooksDir, hook.file);
    if (!existsSync(path) || !commandMatches(hook, input)) continue;
    const result = await runProcess("/bin/bash", [path], {
      cwd,
      env: hookEnv(runtime),
      timeoutMs,
      ...signal && { signal },
      stdin: JSON.stringify({ hook_event_name: "PreToolUse", tool_name: toolName, tool_input: input, cwd })
    });
    if (signal?.aborted) return deny("hook execution interrupted", input, warnings);
    if (result.code === 2) return deny(result.stderr.trim(), input, warnings);
    if (result.code !== 0) {
      const error = `hook failed (exit ${result.code}): ${hook.file}: ${result.stderr.trim()}`;
      if (hook.required) return deny(`required security ${error}`, input, warnings);
      warnings.push(error);
      continue;
    }
    const stdout = result.stdout.trim();
    if (!stdout) continue;
    let parsed;
    try {
      parsed = JSON.parse(stdout);
    } catch {
      const error = `hook stdout is not JSON: ${hook.file}`;
      if (hook.required) return deny(`required security ${error}`, input, warnings);
      warnings.push(error);
      continue;
    }
    let output;
    try {
      output = parseHookOutput(parsed);
    } catch {
      const reason2 = `hook output is invalid: ${hook.file}`;
      if (hook.required) return deny(`required security ${reason2}`, input, warnings);
      warnings.push(reason2);
      continue;
    }
    if (!output) continue;
    const reason = output.permissionDecisionReason ?? "";
    if (output.permissionDecision === "deny") return deny(reason, input, warnings);
    if (output.permissionDecision === "ask") askReasons.push(reason);
    if (output.updatedInput) input = { ...input, ...output.updatedInput };
    if (hook.file === "block-dangerous-in-bash.sh" && output.updatedInput) {
      if (frozenCommand !== void 0 || typeof input.command !== "string") {
        return deny("comment execution binding invalid", input, warnings);
      }
      frozenCommand = input.command;
    }
    if (frozenCommand !== void 0 && input.command !== frozenCommand) {
      return deny("frozen comment payload rewritten; execution blocked", input, warnings);
    }
  }
  if (frozenCommand !== void 0) Object.freeze(input);
  return askReasons.length > 0 ? { decision: "ask", reason: askReasons.join("\n"), finalInput: input, warnings } : { decision: "allow", reason: "", finalInput: input, warnings };
}
function createHookRunner({
  runtime,
  hooksDir = DEFAULT_HOOKS_DIR,
  tablePath = DEFAULT_TABLE_PATH,
  timeoutMs = DEFAULT_TIMEOUT_MS
}) {
  let pipeline;
  let loadError = "";
  try {
    pipeline = loadPipeline(tablePath);
  } catch (error) {
    loadError = message(error);
  }
  return {
    runtime,
    hooksDir,
    hooks(toolName) {
      return pipeline ? selectHooks(pipeline, runtime, toolName).map((hook) => hook.file) : [];
    },
    async preToolUse(toolName, toolInput, cwd, { signal } = {}) {
      if (!pipeline) return deny(`hook pipeline unavailable: ${loadError}`, {}, []);
      if (signal?.aborted) return deny("hook execution interrupted", {}, []);
      try {
        return await evaluate(pipeline, runtime, hooksDir, timeoutMs, toolName, toolInput, cwd, signal);
      } catch (error) {
        return deny(`hook execution failed: ${message(error)}`, {}, []);
      }
    }
  };
}
export {
  DEFAULT_HOOKS_DIR,
  DEFAULT_MAX_OUTPUT_BYTES,
  DEFAULT_TABLE_PATH,
  DEFAULT_TIMEOUT_MS,
  createHookRunner,
  loadPipeline,
  normalizeShellCommand,
  runProcess,
  selectHooks
};

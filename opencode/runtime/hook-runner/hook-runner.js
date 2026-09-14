/**
 * hookRunner — Claude Code の PreToolUse hook（packages/core/hooks/*.sh）を
 * Claude 以外の runtime（pi / omp / opencode）で無改修実行する共有 module。
 *
 * interface は 1 本: createHookRunner({ runtime }).preToolUse(toolName, toolInput, cwd)
 * が decision（allow / deny / ask）と最終 tool_input を返す。以下はすべてこの module の
 * 内側にあり、runtime adapter（pi-extensions / omp-extensions / opencode-plugins）は
 * 知らなくてよい:
 *   - どの hook をどの順で流すか: policy/hook-pipeline.json（SSOT table）を実行時に読む
 *     （runtimes / when.tools / when.commandEre / order）。adapter が hook 一覧を持たない
 *   - wire protocol: stdin JSON {hook_event_name, tool_name, tool_input, cwd}、
 *     exit 2 = deny（stderr が理由）、stdout JSON の hookSpecificOutput.permissionDecision
 *     deny / ask、updatedInput は後続 hook へ連鎖
 *   - fail-closed 規律: table の required: true（deny 能力を持つ security-critical hook）は
 *     「ファイル欠落 / exit 0・2 以外 / stdout が非空なのに JSON でない」を deny に倒す。
 *     advisory hook（required 省略）は warning を集めて続行する
 *   - spawn の作法: /bin/bash、HARNESS_RUNTIME、PATH に /bin・/usr/bin を保証、
 *     60 秒で SIGKILL、stdin の EPIPE 無視、spawn 失敗（cwd 不在等）は hook 失敗扱い
 *
 * 配布レイアウトの契約: この file は各 runtime の configDir 配下で
 *   <root>/hook-runner/hook-runner.js
 *   <root>/claude-hooks/*.sh            ← DEFAULT_HOOKS_DIR
 *   <root>/policy/hook-pipeline.json    ← DEFAULT_TABLE_PATH
 * に並ぶ（pi / omp は configDir 直下、opencode は runtime/ 配下。相対関係は同じ）。
 * hook 自身も $HOOK_DIR/../policy/ と $HOOK_DIR/lib/ を相対参照する。
 *
 * codex は Python（packages/runtimes/codex/harunon-core/scripts/codex_hook.py）が
 * 同じ table を読む第 2 実装。JS に寄せられないため table を共有点にする。
 * SSOT: harunon-harness packages/core/hook-runner/
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DEFAULT_HOOKS_DIR = join(HERE, "..", "claude-hooks");
export const DEFAULT_TABLE_PATH = join(HERE, "..", "policy", "hook-pipeline.json");
export const DEFAULT_TIMEOUT_MS = 60_000;

/**
 * hook-pipeline.json を読む。読めなければ throw（fail loud）。
 * 判定基準が静かに欠けて security-critical hook が fail-open するより、
 * adapter のロードごと失敗させる方が安全（confirm-destructive.ts と同じ方針）。
 */
export function loadPipeline(tablePath = DEFAULT_TABLE_PATH) {
  try {
    return JSON.parse(readFileSync(tablePath, "utf8"));
  } catch (error) {
    throw new Error(`hook-runner: hook-pipeline.json を読み込めません（${tablePath}）: ${error.message}`);
  }
}

/** runtime に配線され、Claude ツール名 toolName に掛かる PreToolUse hook を order 昇順で返す。 */
export function selectHooks(table, runtime, toolName) {
  return table.hooks
    .filter(
      (hook) =>
        hook.runtimes.includes(runtime) &&
        (hook.event ?? "PreToolUse") === "PreToolUse" &&
        (hook.when?.tools ?? []).includes(toolName),
    )
    .sort((a, b) => a.order - b.order);
}

function commandMatches(hook, input) {
  const ere = hook.when?.commandEre;
  if (!ere) return true;
  return new RegExp(ere).test(typeof input.command === "string" ? input.command : "");
}

function hookEnv(runtime) {
  const entries = (process.env.PATH ?? "").split(":").filter(Boolean);
  for (const entry of ["/bin", "/usr/bin"]) {
    if (!entries.includes(entry)) entries.push(entry);
  }
  return { ...process.env, PATH: entries.join(":"), HARNESS_RUNTIME: runtime };
}

/**
 * 子プロセスを 1 つ走らせ {code, stdout, stderr} を返す。reject しない:
 * spawn 自体の失敗（cwd 不在の ENOENT 等）は code 1 + stderr に載せて hook 失敗と同じ経路に流す
 * （listener が無いと unhandled 'error' で拡張ホストごと落ちる）。
 */
export function runProcess(file, args, { cwd, env, stdin, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    const child = spawn(file, args, {
      cwd,
      env,
      stdio: [stdin === undefined ? "ignore" : "pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: 1, stdout: "", stderr: `spawn failed (cwd=${cwd}): ${error.message}` });
    });
    if (stdin !== undefined) {
      // hook が stdin を読み切らず終了すると write が EPIPE になる（deny 系 hook で頻出）。
      // 判定は exit code / stdout で受け取るため、stdin の書き込みエラーは無視してよい。
      child.stdin.on("error", () => {});
      child.stdin.end(stdin);
    }
  });
}

/**
 * @param {{ runtime: string, hooksDir?: string, tablePath?: string, timeoutMs?: number }} options
 *   runtime: HARNESS_RUNTIME と table の runtimes 照合に使う名前（pi / omp / opencode）
 */
export function createHookRunner({
  runtime,
  hooksDir = DEFAULT_HOOKS_DIR,
  tablePath = DEFAULT_TABLE_PATH,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  const table = loadPipeline(tablePath);

  const deny = (reason, finalInput, warnings) => ({ decision: "deny", reason, finalInput, warnings });

  return {
    runtime,
    hooksDir,
    /** toolName に掛かる hook の file 名（order 順）。adapter / テストの観測用。 */
    hooks(toolName) {
      return selectHooks(table, runtime, toolName).map((hook) => hook.file);
    },
    /**
     * @returns {Promise<{decision: "allow"|"deny"|"ask", reason: string, finalInput: object, warnings: string[]}>}
     */
    async preToolUse(toolName, toolInput, cwd) {
      const selected = selectHooks(table, runtime, toolName);
      let input = { ...toolInput };
      const warnings = [];
      const askReasons = [];

      // required hook の実体欠落は、コマンド内容に関係なく deny する（配布漏れで guard が
      // 丸ごと無効化される穴を黙って通さない）。
      const missing = selected.filter((hook) => hook.required && !existsSync(join(hooksDir, hook.file)));
      if (missing.length > 0) {
        return deny(
          `required security hook missing: ${missing.map((h) => h.file).join(", ")} (${hooksDir}) — ` +
            `scripts/install.sh ${runtime}（slim）または配布元 repo で scripts/bootstrap.sh --targets ${runtime} を実行して hooks を再配布してください`,
          input,
          warnings,
        );
      }

      for (const hook of selected) {
        const path = join(hooksDir, hook.file);
        if (!existsSync(path)) continue; // advisory hook の欠落は従来通り skip
        if (!commandMatches(hook, input)) continue;
        const required = hook.required === true;
        const stdin = JSON.stringify({
          hook_event_name: "PreToolUse",
          tool_name: toolName,
          tool_input: input,
          cwd,
        });
        const result = await runProcess("/bin/bash", [path], {
          cwd,
          env: hookEnv(runtime),
          stdin,
          timeoutMs,
        });

        if (result.code === 2) {
          return deny(result.stderr.trim(), input, warnings);
        }
        if (result.code !== 0) {
          const message = `hook failed (exit ${result.code}): ${hook.file}: ${result.stderr.trim()}`;
          if (required) return deny(`required security ${message}`, input, warnings);
          warnings.push(message);
          continue;
        }
        const stdout = result.stdout.trim();
        if (!stdout) continue;
        let parsed;
        try {
          parsed = JSON.parse(stdout);
        } catch {
          if (required) {
            return deny(`required security hook stdout is not JSON: ${hook.file}`, input, warnings);
          }
          warnings.push(`hook stdout is not JSON: ${hook.file}`);
          continue;
        }
        const output = parsed.hookSpecificOutput;
        if (!output) continue;
        const reason = output.permissionDecisionReason ?? "";
        if (output.permissionDecision === "deny") {
          return deny(reason, input, warnings);
        }
        if (output.permissionDecision === "ask") {
          askReasons.push(reason);
        }
        if (output.updatedInput) {
          input = { ...input, ...output.updatedInput };
        }
      }

      if (askReasons.length > 0) {
        return { decision: "ask", reason: askReasons.join("\n"), finalInput: input, warnings };
      }
      return { decision: "allow", reason: "", finalInput: input, warnings };
    },
  };
}

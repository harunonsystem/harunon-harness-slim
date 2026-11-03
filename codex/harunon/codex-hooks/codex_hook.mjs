/**
 * Codex の hook event を hookRunner（../hook-runner/hook-runner.js）へ渡す adapter。
 *
 * wire protocol・hook 選択・required の fail-closed は hookRunner が持つ。ここが持つのは
 * Codex 固有の差だけ（scripts/tests/fixtures/hook-protocol.json に divergence として宣言）:
 * - PreToolUse の permissionDecision:ask を Codex は unsupported として拒否する
 *   （codex-cli 0.146.1 "unsupported permissionDecision:ask"）ので deny に倒す
 * - updatedInput は permissionDecision:allow と対でしか受理されない
 * - deny は exit 0 + hookSpecificOutput で返す
 * SSOT: harunon-harness packages/runtimes/codex/codex-hooks/
 * 配布先は ~/.codex/harunon/codex-hooks/。隣の hook-runner/ claude-hooks/ policy/ は pi と同じ配置。
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHookRunner } from "../hook-runner/hook-runner.js";
import { postEditFindings } from "../hook-runner/post-edit.js";
import { normalizeToolCall } from "../hook-runner/runtime-mapping.js";
import { gateToolCall } from "../policy/publication-gate.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HOOKS_DIR = join(ROOT, "claude-hooks");
const TABLE_PATH = join(ROOT, "policy", "hook-pipeline.json");
const PATCH_FILE_RE = /^\*\*\* (?:Update|Add) File: (.+)$/gm;

function denyWith(reason) {
  return { hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: reason } };
}

const deny = (reason) => denyWith(`Core Workflow blocked shell.guard: ${reason}`);

function isDirectory(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

async function preToolUse(event, runner = createHookRunner({ runtime: "codex", hooksDir: HOOKS_DIR, tablePath: TABLE_PATH })) {
  const toolName = String(event.tool_name ?? event.tool ?? "").toLowerCase();
  const baseCwd = typeof event.cwd === "string" && event.cwd ? event.cwd : process.cwd();
  const normalized = normalizeToolCall("codex", toolName, event.tool_input ?? {}, baseCwd);
  if (!normalized) {
    // hook-pipeline は shell / 編集 tool だけを扱う。GitHub MCP の PR 作成・merge は Bash の
    // gh pr と同じ publication gate に通す（config.toml の [hooks] matcher が mcp__.*github.* を流す）
    const verdict = await gateToolCall({ toolName: event.tool_name ?? event.tool, input: event.tool_input, cwd: baseCwd });
    return verdict && !verdict.allowed ? denyWith(verdict.reason) : undefined;
  }
  // 存在しない cwd で spawn すると advisory hook が warning で素通りするので、先に deny に倒す
  if (!isDirectory(normalized.cwd)) return deny(`セッションの base cwd が存在しません: ${normalized.cwd}`);
  const result = await runner.preToolUse(normalized.toolName, normalized.input, normalized.cwd);
  for (const warning of result.warnings) process.stderr.write(`warning: ${warning}\n`);
  if (result.decision !== "allow") return deny(result.reason);
  if (JSON.stringify(result.finalInput) === JSON.stringify(normalized.input)) return undefined;
  return {
    hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "allow", updatedInput: result.finalInput },
  };
}

/** PostToolUse が触ったファイル（apply_patch は patch envelope から抽出）。 */
function editedPaths(toolInput) {
  const direct = toolInput?.file_path ?? toolInput?.path;
  if (typeof direct === "string") return [direct];
  const patch = toolInput?.patch ?? toolInput?.input ?? "";
  if (typeof patch !== "string") return [];
  return [...patch.matchAll(PATCH_FILE_RE)].map((match) => match[1].trim());
}

async function postToolUse(event) {
  const toolName = String(event.tool_name ?? event.tool ?? "").toLowerCase();
  const baseCwd = typeof event.cwd === "string" && event.cwd ? event.cwd : process.cwd();
  // 相対パスは PreToolUse と同じく tool_input の workdir / cwd を基準に解決する
  const mapped = normalizeToolCall("codex", toolName, event.tool_input ?? {}, baseCwd);
  if (!mapped || !["Write", "Edit"].includes(mapped.toolName) || !existsSync(HOOKS_DIR)) return undefined;
  const findings = [];
  for (const raw of editedPaths(event.tool_input)) {
    const path = isAbsolute(raw) ? raw : resolve(mapped.cwd, raw);
    const text = await postEditFindings(path, { hooksDir: HOOKS_DIR });
    if (text) findings.push(`${raw}\n${text}`);
  }
  if (findings.length === 0) return undefined;
  return {
    hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: `[post-edit-check]\n${findings.join("\n\n")}` },
  };
}

// config.toml の [hooks] が直接起動する entry。entry 判定は持たない（外れると無出力 = 素通りになる）
let output;
try {
  const event = JSON.parse(readFileSync(0, "utf8"));
  output = event.hook_event_name === "PostToolUse" ? await postToolUse(event) : await preToolUse(event);
} catch (error) {
  // 判定できないまま exit 1 で返すと Codex は tool を実行する。guard の失敗は deny に倒す
  output = deny(`codex hook adapter failed: ${error instanceof Error ? error.message : String(error)}`);
}
if (output) process.stdout.write(`${JSON.stringify(output)}\n`);

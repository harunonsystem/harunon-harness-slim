/**
 * Claude Code hooks を pi 上で無改修実行する adapter。
 * pi の tool_call イベントを Claude ツール名 / tool_input に変換して hookRunner
 * （../hook-runner/hook-runner.js）へ渡し、decision を pi の block / confirm UI に写す。
 * どの hook をどの順で流すか・wire protocol・fail-closed 規律は hookRunner が持つ
 * （policy/hook-pipeline.json を実行時に読む。pi 側に hook 一覧は無い）。
 * SSOT: harunon-harness packages/core/pi-extensions/
 * 設計: docs/plans/004-pi-target-bridge.md
 */
import { resolve as resolvePath } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createHookRunner } from "../hook-runner/hook-runner.js";

export interface HookRunResult {
	decision: "allow" | "deny" | "ask";
	reason: string;
	finalInput: Record<string, unknown>;
	warnings: string[];
}

/** hookRunner の interface のうち adapter が使う部分。 */
export interface HookRunner {
	preToolUse(
		toolName: string,
		toolInput: Record<string, unknown>,
		cwd: string,
	): Promise<HookRunResult>;
}

/**
 * pi のツール名 → Claude Code のツール名。
 * pi-codex-conversion 導入下では bash/edit/write/read が exec_command/apply_patch に
 * 置き換わる（bash と exec_command が並存する構成もあるため両方残す）。マップ漏れは
 * ガードのすり抜けに直結する（2026-08-14: apply_patch が block-edit-on-main を素通りした
 * インシデント）。
 */
export const PI_TO_CLAUDE_TOOL: Record<string, string> = {
	bash: "Bash",
	edit: "Edit",
	write: "Write",
	read: "Read",
	exec_command: "Bash",
	interactive_shell: "Bash",
	apply_patch: "Write",
};

/** pi の edit/write/read は `path`、Claude hooks は `tool_input.file_path` を読む */
const PATH_FIELD_TOOLS = new Set(["edit", "write", "read"]);

/** pi の exec_command は `cmd`、Claude の Bash hooks は `tool_input.command` を読む */
const COMMAND_FIELD_TOOLS = new Set(["exec_command"]);

export function toClaudeInput(
	piToolName: string,
	input: Record<string, unknown>,
): Record<string, unknown> {
	if (PATH_FIELD_TOOLS.has(piToolName) && typeof input.path === "string") {
		const { path, ...rest } = input;
		return { ...rest, file_path: path };
	}
	if (COMMAND_FIELD_TOOLS.has(piToolName) && typeof input.cmd === "string") {
		const { cmd, ...rest } = input;
		return { ...rest, command: cmd };
	}
	return { ...input };
}

export function toPiInput(
	piToolName: string,
	claudeInput: Record<string, unknown>,
): Record<string, unknown> {
	if (PATH_FIELD_TOOLS.has(piToolName) && typeof claudeInput.file_path === "string") {
		const { file_path: filePath, ...rest } = claudeInput;
		return { ...rest, path: filePath };
	}
	if (COMMAND_FIELD_TOOLS.has(piToolName) && typeof claudeInput.command === "string") {
		const { command, ...rest } = claudeInput;
		return { ...rest, cmd: command };
	}
	return { ...claudeInput };
}

const APPLY_PATCH_BEGIN_MARKER = "*** Begin Patch";
const APPLY_PATCH_END_MARKER = "*** End Patch";

/**
 * pi-codex-conversion は `exec_command` 内で `apply_patch <<'EOF' ... EOF` 形式の
 * heredoc を検出し、ツール名を exec_command のままファイル変更を直接適用する
 * （src/tools/exec/command-tool.ts の interceptApplyPatch /
 * extractPathApplyPatchPreviewInput）。ツール名ベースの matcher では
 * block-edit-on-main 等の Write ガードに一切乗らないため、cmd 文字列に envelope が
 * 含まれるかを別途検査する必要がある（2026-08-14 Codex review P1）。
 * envelope が完全に抽出できない場合（Begin だけで End が無い等）は undefined を返し、
 * 呼び出し側で file_path 無しの素の判定にフォールバックさせる。
 */
export function extractApplyPatchEnvelope(command: string): string | undefined {
	const beginIndex = command.indexOf(APPLY_PATCH_BEGIN_MARKER);
	if (beginIndex === -1) {
		return undefined;
	}
	const endIndex = command.indexOf(APPLY_PATCH_END_MARKER, beginIndex);
	if (endIndex === -1) {
		return undefined;
	}
	return command.slice(beginIndex, endIndex + APPLY_PATCH_END_MARKER.length);
}

export interface ToolCallEvent {
	toolName: string;
	input: Record<string, unknown>;
}

export type ToolCallResponse = { block: true; reason: string } | undefined;

export interface BridgeUi {
	confirm(title: string, message: string): Promise<boolean>;
	notify(message: string, level: "info" | "warning" | "error"): void;
}

export interface BridgeContext {
	hasUI: boolean;
	ui: BridgeUi;
	/** セッションの base cwd（pi ExtensionContext.cwd 相当）。hook の spawn cwd の基準になる。 */
	cwd: string;
}

/**
 * hook へ渡す base cwd を確定する。exec_command の `workdir`（あれば実際の実行 cwd）を
 * 最優先とし、次に `input.cwd` を見る。どちらもセッション base（`ctx.cwd`）基準で解決し
 * （絶対パスならそれが優先される）、どちらも無ければ `ctx.cwd` をそのまま使う。
 * `process.cwd()`（pi プロセス自身の cwd）へのフォールバックは持たない。
 */
function resolveBaseCwd(ctx: BridgeContext, input: Record<string, unknown>): string {
	const workdir = typeof input.workdir === "string" ? input.workdir : undefined;
	const inputCwd = typeof input.cwd === "string" ? input.cwd : undefined;
	const base = workdir ?? inputCwd;
	if (base) {
		return resolvePath(ctx.cwd, base);
	}
	return ctx.cwd;
}

/** runner の decision を pi の応答へ写す。ask は UI 承認で通し、UI が無ければ block に倒す。 */
async function settle(result: HookRunResult, ctx: BridgeContext): Promise<ToolCallResponse> {
	if (ctx.hasUI) {
		for (const warning of result.warnings) {
			ctx.ui.notify(warning, "warning");
		}
	}
	if (result.decision === "deny") {
		return { block: true, reason: result.reason };
	}
	if (result.decision === "ask") {
		const approved = ctx.hasUI && (await ctx.ui.confirm("Hook 確認", result.reason));
		if (!approved) {
			return { block: true, reason: result.reason };
		}
	}
	return undefined;
}

export function createToolCallHandler(runner: HookRunner) {
	return async (event: ToolCallEvent, ctx: BridgeContext): Promise<ToolCallResponse> => {
		const claudeToolName = PI_TO_CLAUDE_TOOL[event.toolName];
		if (!claudeToolName) {
			return undefined;
		}
		const claudeInput = toClaudeInput(event.toolName, event.input);
		const baseCwd = resolveBaseCwd(ctx, event.input);
		const result = await runner.preToolUse(claudeToolName, claudeInput, baseCwd);
		const blocked = await settle(result, ctx);
		if (blocked) {
			return blocked;
		}

		// exec_command は Bash hooks 通過後の最終 cmd に apply_patch heredoc が
		// 埋め込まれている場合がある（pi-codex-conversion が exec_command 内で直接
		// 適用するため、ツール名は exec_command のまま Write ガードに乗らない）。
		// updatedInput は検査専用で反映しない（result.finalInput の書き戻しのみ行う）。
		if (event.toolName === "exec_command") {
			const finalCommand =
				typeof result.finalInput.command === "string" ? result.finalInput.command : "";
			if (finalCommand.includes(APPLY_PATCH_BEGIN_MARKER)) {
				const envelope = extractApplyPatchEnvelope(finalCommand);
				const syntheticInput: Record<string, unknown> =
					envelope !== undefined ? { file_path: "", input: envelope } : { file_path: "" };
				const patchBlocked = await settle(
					await runner.preToolUse("Write", syntheticInput, baseCwd),
					ctx,
				);
				if (patchBlocked) {
					return patchBlocked;
				}
			}
		}

		Object.assign(event.input, toPiInput(event.toolName, result.finalInput));
		return undefined;
	};
}

export default function claudeHooksBridge(pi: ExtensionAPI) {
	pi.on("tool_call", createToolCallHandler(createHookRunner({ runtime: "pi" })));
}

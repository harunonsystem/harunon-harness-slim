/**
 * Claude Code hooks を pi 上で無改修実行する adapter。
 * pi の tool_call イベントを Claude ツール名 / tool_input に変換して hookRunner
 * （../hook-runner/hook-runner.js）へ渡し、decision を pi の block / confirm UI に写す。
 * どの hook をどの順で流すか・wire protocol・fail-closed 規律は hookRunner が持つ
 * （policy/hook-pipeline.json を実行時に読む。pi 側に hook 一覧は無い）。
 * SSOT: harunon-harness packages/core/pi-extensions/
 * 設計: docs/plans/004-pi-target-bridge.md
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createHookRunner } from "../hook-runner/hook-runner.js";
import { normalizeToolCall, restoreToolInput } from "../hook-runner/runtime-mapping.js";

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
		const normalized = normalizeToolCall("pi", event.toolName, event.input, ctx.cwd);
		if (!normalized) {
			return undefined;
		}
		const result = await runner.preToolUse(normalized.toolName, normalized.input, normalized.cwd);
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
					await runner.preToolUse("Write", syntheticInput, normalized.cwd),
					ctx,
				);
				if (patchBlocked) {
					return patchBlocked;
				}
			}
		}

		Object.assign(event.input, restoreToolInput("pi", event.toolName, result.finalInput));
		return undefined;
	};
}

export default function claudeHooksBridge(pi: ExtensionAPI) {
	pi.on("tool_call", createToolCallHandler(createHookRunner({ runtime: "pi" })));
}

/**
 * Claude Code hooks を pi 上で無改修実行する adapter。
 * pi の tool_call イベントを Claude ツール名 / tool_input に変換して hookRunner
 * （../hook-runner/hook-runner.js）へ渡し、decision を pi の block / confirm UI に写す。
 * どの hook をどの順で流すか・wire protocol・fail-closed 規律は hookRunner が持つ
 * （policy/hook-pipeline.json を実行時に読む。pi 側に hook 一覧は無い）。
 * tool 形の変換・apply_patch envelope の切り出し・decision の写し方は omp adapter と共通の
 * ../hook-runner/runtime-mapping.js が持つ。
 * SSOT: harunon-harness packages/core/pi-extensions/
 * 設計: docs/plans/004-pi-target-bridge.md
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createHookRunner } from "../hook-runner/hook-runner.js";
import {
	extractApplyPatchEnvelope,
	normalizeToolCall,
	restoreToolInput,
	settleDecision,
} from "../hook-runner/runtime-mapping.js";

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

export function createToolCallHandler(runner: HookRunner) {
	return async (event: ToolCallEvent, ctx: BridgeContext): Promise<ToolCallResponse> => {
		const normalized = normalizeToolCall("pi", event.toolName, event.input, ctx.cwd);
		if (!normalized) {
			return undefined;
		}
		const result = await runner.preToolUse(normalized.toolName, normalized.input, normalized.cwd);
		const blocked = await settleDecision(result, ctx);
		if (blocked) {
			return blocked;
		}

		// pi-codex-conversion は exec_command 内の `apply_patch <<'EOF' ... EOF` を
		// ツール名 exec_command のまま直接適用する（src/tools/exec/command-tool.ts の
		// interceptApplyPatch）ため、Bash hooks 通過後の最終 cmd に envelope があれば
		// Write hooks にも envelope で渡す（block-edit-on-main が envelope から対象 path を取る）。
		// envelope が切り出せない（End が無い等）ときは file_path 無しで渡し、hook 側の
		// fail-closed（cwd を対象にする）に委ねる。updatedInput は検査専用で反映しない。
		if (event.toolName === "exec_command") {
			const finalCommand =
				typeof result.finalInput.command === "string" ? result.finalInput.command : "";
			if (finalCommand.includes("*** Begin Patch")) {
				const envelope = extractApplyPatchEnvelope(finalCommand);
				const syntheticInput: Record<string, unknown> =
					envelope !== undefined ? { file_path: "", input: envelope } : { file_path: "" };
				const patchBlocked = await settleDecision(
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

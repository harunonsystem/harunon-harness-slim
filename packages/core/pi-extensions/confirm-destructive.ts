/**
 * pi には Claude Code の permission 層（settings の allow/deny/ask）が存在しないため、
 * その欠落を補う pi 専用の破壊的コマンド確認レイヤー。
 * TUI では confirm ダイアログ、非対話（-p / rpc）では安全側に倒して block する。
 * git 系の細かいガードは claude-hooks-bridge 側の block-dangerous-in-bash.sh が担当し、
 * ここは「Claude Code なら permission ask になっていた操作」だけを扱う。
 *
 * RULES は packages/core/policy/danger-rules.json（危険コマンドルール SSOT）から
 * 実行時に読み込む。table の schema・他表現との整合は
 * scripts/harness_lib/danger_rules.py が検証する。table が読めない、または
 * pi 対象の rule が0件の場合は拡張のロード自体を失敗させる（fail-loud。
 * 確認ダイアログ層が黙って消える事故を防ぐ）。
 * SSOT: harunon-harness packages/core/pi-extensions/
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	PI_TO_CLAUDE_TOOL,
	toClaudeInput,
	type BridgeContext,
	type ToolCallEvent,
	type ToolCallResponse,
} from "./claude-hooks-bridge.ts";

interface Rule {
	pattern: RegExp;
	reason: string;
}

interface DangerRuleMatch {
	js?: string;
	jsFlags?: string;
	origin?: string;
}

interface DangerRule {
	id: string;
	message?: string;
	targets?: string[];
	match?: DangerRuleMatch;
}

interface DangerRulesTable {
	constants: { originJs?: string };
	rules: DangerRule[];
}

const TABLE_PATH = fileURLToPath(new URL("../policy/danger-rules.json", import.meta.url));

function originPrefix(originKind: string, originJs: string): string {
	if (originKind === "default") return originJs;
	if (originKind === "none") return "";
	throw new Error(`confirm-destructive: 未対応の match.origin です: ${originKind}`);
}

function loadRules(): Rule[] {
	let table: DangerRulesTable;
	try {
		table = JSON.parse(readFileSync(TABLE_PATH, "utf8"));
	} catch (error) {
		throw new Error(
			`confirm-destructive: danger-rules.json を読み込めません（${TABLE_PATH}）: ${(error as Error).message}`,
		);
	}

	const originJs = table.constants?.originJs ?? "";
	const rules: Rule[] = [];
	for (const rule of table.rules) {
		const targets = rule.targets;
		if (!targets) {
			throw new Error(`confirm-destructive: rule "${rule.id}" に targets がありません`);
		}
		if (!targets.includes("pi")) continue;
		const js = rule.match?.js;
		if (!js) continue;
		if (!rule.message) {
			throw new Error(`confirm-destructive: rule "${rule.id}" に message がありません`);
		}
		const prefix = originPrefix(rule.match?.origin ?? "default", originJs);
		rules.push({
			pattern: new RegExp(prefix + js, rule.match?.jsFlags ?? ""),
			reason: rule.message,
		});
	}

	if (rules.length === 0) {
		throw new Error(
			`confirm-destructive: danger-rules.json に pi 対象の rule がありません（${TABLE_PATH}）`,
		);
	}
	return rules;
}

const RULES: Rule[] = loadRules();

export function destructiveReason(command: string): string | undefined {
	for (const rule of RULES) {
		if (rule.pattern.test(command)) {
			return rule.reason;
		}
	}
	return undefined;
}

export function createConfirmDestructiveHandler() {
	return async (event: ToolCallEvent, ctx: BridgeContext): Promise<ToolCallResponse> => {
		if (PI_TO_CLAUDE_TOOL[event.toolName] !== "Bash") {
			return undefined;
		}
		const claudeInput = toClaudeInput(event.toolName, event.input);
		const command = typeof claudeInput.command === "string" ? claudeInput.command : "";
		const reason = destructiveReason(command);
		if (!reason) {
			return undefined;
		}
		const approved =
			ctx.hasUI && (await ctx.ui.confirm("破壊的コマンドの確認", `${reason}\n$ ${command}`));
		if (!approved) {
			return { block: true, reason: `ユーザー未承認: ${reason}` };
		}
		return undefined;
	};
}

export default function confirmDestructive(pi: ExtensionAPI) {
	pi.on("tool_call", createConfirmDestructiveHandler());
}

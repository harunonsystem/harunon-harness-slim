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
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { normalizeToolCall } from "../hook-runner/runtime-mapping.js";
import type {
	BridgeContext,
	ToolCallEvent,
	ToolCallResponse,
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

export interface ToolAnnotations {
	readOnlyHint?: boolean;
	destructiveHint?: boolean;
	openWorldHint?: boolean;
}

// ponytail: jev-mcp 0.11 は annotation を宣言しないが副作用のない評価器なので、harness 配布の jev の既知 tool だけ固定で除外する。
// jev の tool が増えたらここを更新する。
const READ_ONLY_MCP_TOOLS = new Set(
	["audit", "classify", "compare", "decide", "extract", "find", "gate", "noul", "rerank", "review", "screen", "verify"].map(
		(name) => `mcp__jev__jev_${name}`,
	),
);

/**
 * 信頼済み project の .pi/mcp.json は同名の global server を置き換えるので、
 * project が jev を定義していれば同名 tool でも harness 配布の jev とはみなさない。
 * 読めない・壊れた file も上書きの可能性を否定できないため同様に扱う。
 */
export function projectOverridesJev(cwd: string): boolean {
	const path = join(cwd, ".pi", "mcp.json");
	if (!existsSync(path)) return false;
	try {
		return JSON.parse(readFileSync(path, "utf8"))?.mcpServers?.jev !== undefined;
	} catch {
		return true;
	}
}

/**
 * MCP tool annotation から確認要否を決める（Pi docs の Codex 相当ルール）。
 * hint が無い tool は MCP 既定どおり「書き込みあり・外部到達あり」とみなす。
 */
export function mcpNeedsApproval(
	toolName: string,
	hints: ToolAnnotations | undefined,
	jevOverridden = false,
): boolean {
	if (hints?.destructiveHint === true) return true;
	if (!jevOverridden && READ_ONLY_MCP_TOOLS.has(toolName)) return false;
	return !hints?.readOnlyHint && ((hints?.destructiveHint ?? true) || (hints?.openWorldHint ?? true));
}

async function confirmOrBlock(
	ctx: BridgeContext,
	title: string,
	reason: string,
	detail: string,
): Promise<ToolCallResponse> {
	const approved = ctx.hasUI && (await ctx.ui.confirm(title, `${reason}\n${detail}`));
	return approved ? undefined : { block: true, reason: `ユーザー未承認: ${reason}` };
}

export function createConfirmDestructiveHandler(
	annotationsOf: (toolName: string) => ToolAnnotations | undefined = () => undefined,
) {
	return async (event: ToolCallEvent, ctx: BridgeContext): Promise<ToolCallResponse> => {
		// codemode script 内の MCP 呼び出しも個別の tool_call で届くため、codemode tool 自体は判定しない。
		if (event.toolName.startsWith("mcp__")) {
			const cwd = ctx.cwd ?? process.cwd();
			const hints = annotationsOf(event.toolName);
			if (!mcpNeedsApproval(event.toolName, hints, projectOverridesJev(cwd))) return undefined;
			return confirmOrBlock(
				ctx,
				"MCP ツールの確認",
				"read-only と宣言されていない MCP ツールです",
				`${event.toolName} ${JSON.stringify(event.input)}`,
			);
		}
		const normalized = normalizeToolCall("pi", event.toolName, event.input, ctx.cwd ?? process.cwd());
		if (!normalized || normalized.toolName !== "Bash") {
			return undefined;
		}
		const command = typeof normalized.input.command === "string" ? normalized.input.command : "";
		const reason = destructiveReason(command);
		if (!reason) {
			return undefined;
		}
		return confirmOrBlock(ctx, "破壊的コマンドの確認", reason, `$ ${command}`);
	};
}

export default function confirmDestructive(pi: ExtensionAPI) {
	pi.on(
		"tool_call",
		createConfirmDestructiveHandler(
			(toolName) => pi.getAllTools().find((tool) => tool.name === toolName)?.annotations,
		),
	);
}

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
import { normalizeShellCommand } from "../hook-runner/hook-runner.js";
import { normalizeToolCall } from "../hook-runner/runtime-mapping.js";
import type {
	BridgeContext,
	ToolCallEvent,
	ToolCallResponse,
} from "./claude-hooks-bridge.ts";

interface Rule {
	id: string;
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
			id: rule.id,
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

function shellUnits(command: string): { text: string; stdin: string }[] {
	// Keep quoted separators in their argument; never execute the source text.
	const units: { text: string; stdin: string }[] = [];
	let start = 0;
	let quote = "";
	let stdin = "";
	let groupDepth = 0;
	let stdoutEaten = false;
	for (let index = 0; index < command.length; index++) {
		const char = command[index];
		if (char === "\\" && quote !== "'") { index++; continue; }
		if (quote) {
			if (char === quote) quote = "";
			continue;
		}
		if (char === "'" || char === '"' || char === "`") { quote = char; continue; }
		// A grouped producer must reach the downstream SQL client as a whole.
		// Keep opaque grouped syntax conservative instead of dropping its input.
		if (char === "(" || char === "{") { groupDepth++; continue; }
		if (char === ")" || char === "}") { groupDepth = Math.max(0, groupDepth - 1); continue; }
		// `&` glued to a redirect is not a separator: `2>&1` / `0<&1` duplicate fds and
		// `&>` / `&>>` redirect both streams. Splitting there loses the producer.
		if (char === "&") {
			if (command[index + 1] === ">") { if (groupDepth === 0) stdoutEaten = true; continue; }
			if (command[index - 1] === ">" || command[index - 1] === "<") continue;
		}
		// `>` / `1>` / `>&` send stdout away from the pipe; `2>` / `2>&1` do not.
		// Fds above 9 are rare; scan the whole digit run before `>`.
		if (char === ">" && groupDepth === 0) {
			const prev = command[index - 1];
			if (prev !== "&" && prev !== ">") {
				let back = index - 1;
				while (back >= 0 && command[back] >= "0" && command[back] <= "9") back--;
				if (back === index - 1 || Number(command.slice(back + 1, index)) === 1) stdoutEaten = true;
			}
			continue;
		}
		if (groupDepth === 0 && ";&|\n".includes(char)) {
			const text = command.slice(start, index);
			units.push({ text, stdin });
			// A producer's data is executable SQL for a downstream database client.
			// Conditional || is not a pipe; following commands never supply input.
			stdin = char === "|" && command[index + 1] !== "|" && !stdoutEaten ? `${stdin}\n${text}` : "";
			if (char === "|" && (command[index + 1] === "|" || command[index + 1] === "&")) index++;
			stdoutEaten = false;
			start = index + 1;
		}
	}
	units.push({ text: command.slice(start), stdin });
	return units.filter((unit) => unit.text.trim());
}

export function destructiveReason(command: string): string | undefined {
	let normalized: string;
	try { normalized = normalizeShellCommand(command); }
	catch { return "コマンドの安全判定に必要な正規化が利用できません"; }
	for (const rule of RULES) {
		// SQL text is data to the shell but executable to a database client.
		if (rule.pattern.test(normalized)) {
			return rule.reason;
		}
		if (rule.id === "sql-drop") {
			for (const unit of shellUnits(command)) {
				let rendered: string;
				try { rendered = normalizeShellCommand(unit.text); }
				catch { return "コマンドの安全判定に必要な正規化が利用できません"; }
				const sqlClient = /(?:^|[;&|\n])\s*(?:[^\s;|&]*\/)?(?:psql|mysql|sqlite3)(?=\s|$)/.test(rendered);
				if (sqlClient && rule.pattern.test(`${unit.stdin}\n${unit.text}`)) return rule.reason;
			}
		}
	}
	return undefined;
}

export interface ToolAnnotations {
	readOnlyHint?: boolean;
	destructiveHint?: boolean;
	openWorldHint?: boolean;
}

/**
 * MCP tool annotation から確認要否を決める（Pi docs の Codex 相当ルール）。
 * hint が無い tool は MCP 既定どおり「書き込みあり・外部到達あり」とみなす。
 */
export function mcpNeedsApproval(hints: ToolAnnotations | undefined): boolean {
	if (hints?.destructiveHint === true) return true;
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
			const hints = annotationsOf(event.toolName);
			if (!mcpNeedsApproval(hints)) return undefined;
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

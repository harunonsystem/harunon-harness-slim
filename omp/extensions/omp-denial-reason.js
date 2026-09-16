/**
 * omp の tool_call を hookRunner（../hook-runner/hook-runner.js）へ渡す adapter。
 *
 * omp の危険コマンド判定は config.yml の bash.patterns（danger-rules.json 由来の glob）が
 * 担うが、glob deny はメッセージを運べず、エージェントには「denied」しか見えない
 * （approve-push.sh を実行する / SSOT を直す、といった次の行動が学べない）。
 * この extension は tool_call ごとに hookRunner を HARNESS_RUNTIME=omp で走らせ、
 * deny のとき hook の理由（rule の message = 次の行動）で block する。allow なら
 * 何もしない（deny の主体は引き続き bash.patterns。ここは説明と第二防衛線）。
 * omp に配線される hook は policy/hook-pipeline.json の runtimes が決める
 * （required なので配布漏れは hookRunner が deny に倒す）。
 *
 * omp 固有の差（scripts/tests/fixtures/hook-protocol.json に divergence として宣言）:
 * 確認 UI を持たないため ask は block に倒す。updatedInput は ToolCallEventResult.input
 * で書き戻す（rtk-rewrite が omp に配線される）。
 * SSOT: harunon-harness packages/core/omp-extensions/
 */
import { resolve as resolvePath } from "node:path";
import { createHookRunner } from "../hook-runner/hook-runner.js";

/**
 * omp のツール名 → Claude Code のツール名。
 * bash だけでなく edit / write / read / apply_patch / exec_command も
 * 各 Claude ツール名へ写し、Write ガードや Bash ガードを適用する。
 */
const OMP_TO_CLAUDE_TOOL = {
	bash: "Bash",
	edit: "Edit",
	write: "Write",
	read: "Read",
	exec_command: "Bash",
	interactive_shell: "Bash",
	apply_patch: "Write",
};

/** omp の edit/write/read は `path`、Claude hooks は `tool_input.file_path` を読む */
const PATH_FIELD_TOOLS = new Set(["edit", "write", "read"]);

/** omp の exec_command は `cmd`、Claude の Bash hooks は `tool_input.command` を読む */
const COMMAND_FIELD_TOOLS = new Set(["exec_command"]);

function toClaudeInput(ompToolName, input) {
	if (PATH_FIELD_TOOLS.has(ompToolName) && typeof input.path === "string") {
		const { path, ...rest } = input;
		return { ...rest, file_path: path };
	}
	if (COMMAND_FIELD_TOOLS.has(ompToolName) && typeof input.cmd === "string") {
		const { cmd, ...rest } = input;
		return { ...rest, command: cmd };
	}
	return { ...input };
}

/** Claude 形の input を omp 側のフィールド名へ戻す（rewrite 書き戻し用） */
function toOmpInput(ompToolName, claudeInput) {
	if (COMMAND_FIELD_TOOLS.has(ompToolName) && typeof claudeInput.command === "string") {
		const { command, ...rest } = claudeInput;
		return { ...rest, cmd: command };
	}
	return { ...claudeInput };
}

export function createDenialReasonHandler(runner) {
	return async (event, ctx) => {
		const claudeToolName = OMP_TO_CLAUDE_TOOL[event?.toolName];
		if (!claudeToolName) return undefined;
		const input = event.input ?? {};
		// exec_command 系では input.workdir が実際の実行 cwd になることがある。workdir を
		// 無視すると別 repo を指定したコマンドがセッション側 repo の guard を潜り抜けるので、
		// workdir > input.cwd > ctx.cwd で解決する。
		const workdir = typeof input.workdir === "string" ? input.workdir : undefined;
		const inputCwd = typeof input.cwd === "string" ? input.cwd : undefined;
		// ctx.cwd が無い呼び出しでも throw で handler を reject させない（reject 時の扱いは omp 側に委ねない）
		const baseCwd = typeof ctx?.cwd === "string" && ctx.cwd ? ctx.cwd : process.cwd();
		const base = workdir ?? inputCwd;
		const cwd = base ? resolvePath(baseCwd, base) : baseCwd;
		const claudeInput = toClaudeInput(event.toolName, input);
		// Bash 系（bash / exec_command / interactive_shell）は command が無いと
		// 判定不能なので hook を呼ばない。exec_command は cmd → command 変換後に見る。
		if (claudeToolName === "Bash" && typeof claudeInput.command !== "string") return undefined;
		const result = await runner.preToolUse(claudeToolName, claudeInput, cwd);
		if (result.decision !== "allow") {
			return { block: true, reason: result.reason || "harness guard hook が理由なしで deny しました" };
		}

		// rewrite 系 hook（rtk-rewrite）が updatedInput を返したときだけ実行入力を
		// 書き戻す。runner は入力を必ずコピーするので参照ではなく内容で比較する
		// （updatedInput が新しいキーを足せば stringify でも差が出る）。書き戻すのは
		// omp 側のフィールド形（exec_command は cmd）に戻したもの。
		if (JSON.stringify(result.finalInput) !== JSON.stringify(claudeInput)) {
			return { input: toOmpInput(event.toolName, result.finalInput) };
		}
		return undefined;
	};
}

export default function ompDenialReason(pi) {
  pi.on("tool_call", createDenialReasonHandler(createHookRunner({ runtime: "omp" })));
}

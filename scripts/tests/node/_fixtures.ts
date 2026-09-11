/**
 * hookRunner / adapter テストの共有 fixture。
 * hook スクリプトと hook-pipeline.json を一時ディレクトリに組み立てる。
 */
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../..");
export const REAL_HOOKS_DIR = join(REPO_ROOT, "packages/core/hooks");
export const REAL_TABLE_PATH = join(REPO_ROOT, "packages/core/policy/hook-pipeline.json");

export function fixtureScript(dir: string, name: string, body: string): string {
	const path = join(dir, name);
	writeFileSync(path, `#!/usr/bin/env bash\n${body}\n`);
	chmodSync(path, 0o755);
	return path;
}

export interface FixtureHook {
	file: string;
	order?: number;
	required?: boolean;
	tools?: string[];
	commandEre?: string;
	runtimes?: string[];
	stage?: string;
}

const ALL_RUNTIMES = ["pi", "omp", "opencode", "codex"];

/** 最小の hook-pipeline.json を dir に書き、そのパスを返す。 */
export function writeTable(dir: string, hooks: FixtureHook[]): string {
	const table = {
		version: 1,
		stages: ["guard", "rewrite"],
		runtimes: Object.fromEntries(ALL_RUNTIMES.map((r) => [r, { executionModel: "sequential" }])),
		hooks: hooks.map((hook, index) => ({
			id: hook.file.replace(/\.sh$/, ""),
			file: hook.file,
			event: "PreToolUse",
			stage: hook.stage ?? "guard",
			order: hook.order ?? (index + 1) * 10,
			...(hook.required === undefined ? {} : { required: hook.required }),
			when: {
				tools: hook.tools ?? ["Bash"],
				...(hook.commandEre ? { commandEre: hook.commandEre } : {}),
			},
			runtimes: hook.runtimes ?? ALL_RUNTIMES,
		})),
	};
	const path = join(dir, "hook-pipeline.json");
	writeFileSync(path, JSON.stringify(table));
	return path;
}

/** hooks dir と table を持つ一時 fixture。hooks は素通り stub として作る。 */
export function fixtureLayout(prefix: string, hooks: FixtureHook[]): { dir: string; tablePath: string } {
	const dir = mkdtempSync(join(tmpdir(), prefix));
	for (const hook of hooks) {
		fixtureScript(dir, hook.file, "cat > /dev/null\nexit 0");
	}
	return { dir, tablePath: writeTable(dir, hooks) };
}

export function withEnv<T>(name: string, value: string | undefined, fn: () => Promise<T>): Promise<T> {
	const previous = process.env[name];
	if (value === undefined) delete process.env[name];
	else process.env[name] = value;
	return fn().finally(() => {
		if (previous === undefined) delete process.env[name];
		else process.env[name] = previous;
	});
}

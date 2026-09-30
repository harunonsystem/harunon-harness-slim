import { mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import timers from "node:timers/promises";

// ponytail: serialize both accounts; split locks only if refresh contention matters.
// Never steal a timed-out lock: a paused owner may still write rotating tokens.
export async function withCredentialLock(dir, operation) {
	mkdirSync(dir, { recursive: true, mode: 0o700 });
	const lock = join(dir, ".openai-codex-credentials.lock");
	let deadline = Date.now() + 30_000;
	let owner;
	for (;;) {
		try {
			mkdirSync(lock, { mode: 0o700 });
			break;
		} catch (error) {
			if (error.code !== "EEXIST") throw error;
			const holder = statSync(lock, { throwIfNoEntry: false });
			if (!holder) continue;
			const identity = `${holder.dev}:${holder.ino}:${holder.birthtimeMs}`;
			if (identity !== owner) {
				owner = identity;
				deadline = Date.now() + 30_000;
			}
			if (Date.now() >= deadline) {
				throw new Error(`Credential lock timed out: ${lock}; check owner.pid before removing a stale lock`);
			}
			await timers.setTimeout(50);
		}
	}
	try {
		writeFileSync(join(lock, "owner.pid"), `${process.pid}\n`, { mode: 0o600 });
		return await operation();
	} finally {
		rmSync(lock, { recursive: true });
	}
}

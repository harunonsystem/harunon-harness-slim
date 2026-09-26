const PREFIX = "π";
const FALLBACK_TITLE = "π";
const MAX_NAME_LENGTH = 40;
const SPINNER_MS = 140;
const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function basename(path) {
	const trimmed = String(path ?? "").replace(/[\\/]+$/, "");
	return trimmed.split(/[\\/]/).pop() || FALLBACK_TITLE;
}

function truncate(value) {
	if (value.length <= MAX_NAME_LENGTH) return value;
	return `${value.slice(0, MAX_NAME_LENGTH - 3)}...`;
}

export default function terminalStatusTitle(pi) {
	let status = "idle";
	let frame = 0;
	let timer;
	let lastCtx;

	const stopSpinner = () => {
		if (timer) clearInterval(timer);
		timer = undefined;
		frame = 0;
	};

	const writeTitle = (ctx = lastCtx) => {
		if (!ctx?.hasUI) return;
		lastCtx = ctx;
		const sessionName = pi.getSessionName()?.trim();
		const name = truncate(sessionName || basename(ctx.cwd));
		const indicator =
			status === "working" ? SPINNER[frame % SPINNER.length] : status === "done" ? "✓" : "○";
		ctx.ui.setTitle(`${indicator} | ${PREFIX} | ${name}`);
	};

	const setStatus = (next, ctx) => {
		status = next;
		lastCtx = ctx;
		stopSpinner();

		if (status === "working" && ctx?.hasUI) {
			timer = setInterval(() => {
				frame = (frame + 1) % SPINNER.length;
				writeTitle();
			}, SPINNER_MS);
			timer.unref?.();
		}

		writeTitle(ctx);
	};

	const resetForSession = (_event, ctx) => {
		setStatus("idle", ctx);
	};

	pi.on("session_start", resetForSession);
	pi.on("session_switch", resetForSession);
	pi.on("session_fork", resetForSession);

	// Renaming/metadata changes stay in the same session, so preserve the current
	// working/done state and only refresh the visible label.
	pi.on("session_info_changed", async (_event, ctx) => {
		writeTitle(ctx);
	});

	pi.on("agent_start", async (_event, ctx) => {
		setStatus("working", ctx);
	});

	pi.on("agent_settled", async (_event, ctx) => {
		setStatus("done", ctx);
	});

	pi.on("session_shutdown", async () => {
		stopSpinner();
	});
}

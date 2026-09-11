---
description: Run a Codex code review against local git state
argument-hint: '[--wait|--background] [--base <ref>] [--scope auto|working-tree|branch]'
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

Run a Codex review through the shared built-in reviewer.

This user-level command overrides the plugin's `/codex:review` to enforce review-only behavior and background-by-default execution. The default review model is `gpt-5.6-sol` with `medium` reasoning, synchronized from `packages/targets/codex/profiles/review.config.toml`; pass `--model` to override it for one review.

Raw slash-command arguments:
`$ARGUMENTS`

Core constraint:
- This command is review-only.
- Do not fix issues, apply patches, or suggest that you are about to make changes.
- Your only job is to run the review and return Codex's output verbatim to the user.

Execution mode rules:
- Background is the default. Unless the raw arguments include `--wait`, launch the review as a Claude background task.
- If the raw arguments include `--wait`, run the review in the foreground.
- Do not ask which execution mode to use and do not estimate review size first.
- Do not rely on the companion's native `review --background` flag: as of plugin 1.0.6 it is parsed but never checked (`handleReviewCommand` always calls `runForegroundCommand`; only the `task` subcommand implements background enqueue), so it silently runs in the foreground.

Argument handling:
- Preserve the user's arguments exactly.
- Argument safety: the raw arguments are interpolated into a shell command string. Before running, verify every whitespace-separated token consists only of `A-Z a-z 0-9 . _ / @ = -`. If any token contains other characters (quotes, `;`, `&`, `|`, `$`, backticks, parentheses, `<`, `>`, spaces inside a token, etc.), do not run the command; tell the user which token was rejected and ask them to re-run with plain flags.
- Do not strip `--wait` or `--background` yourself.
- Do not add extra review instructions or rewrite the user's intent.
- If the user passes their own `--model`, it is forwarded as-is to the companion script.
- `/codex:review` is native-review only. It does not support staged-only review, unstaged-only review, or extra focus text.
- If the user needs custom review instructions or more adversarial framing, they should use `/codex:adversarial-review`.

Path resolution:
- Resolve the latest installed codex-companion script path dynamically so this override survives plugin version bumps:
```bash
COMPANION=$(ls -t "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1)
```

Background flow (default):
- Launch the review with `Bash` in the background:
```typescript
Bash({
  command: `COMPANION=$(ls -t "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1) && node "$COMPANION" review $ARGUMENTS`,
  description: "Codex review",
  run_in_background: true
})
```
- Do not call `BashOutput` or wait for completion in this turn.
- After launching the command, tell the user: "Codex review started in the background. Check `/codex:status` for progress."

Foreground flow (`--wait` passed):
- Run:
```bash
COMPANION=$(ls -t "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1) && node "$COMPANION" review $ARGUMENTS
```
- Return the command stdout verbatim, exactly as-is.
- Do not paraphrase, summarize, or add commentary before or after it.
- Do not fix any issues mentioned in the review output.

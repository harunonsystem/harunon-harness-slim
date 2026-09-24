---
description: Run a Codex code review against local git state
argument-hint: '[--wait|--background] [--base <ref>] [--scope auto|working-tree|branch]'
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

Run a Codex review through the shared built-in reviewer.

This user-level command overrides the plugin's `/codex:review` to enforce background-by-default execution and to hand the result to the fix flow in `rules/codex-review-policy.md`. The default review model is `gpt-5.6-sol` with `medium` reasoning, synchronized from `packages/targets/codex/profiles/review.config.toml`; pass `--model` to override it for one review.

Raw slash-command arguments:
`$ARGUMENTS`

Core constraint:
- The command itself only runs the review and returns Codex's output verbatim. Do not edit files before the output is back, and do not add review instructions of your own.
- What happens after the output is back is defined by `rules/codex-review-policy.md` (the section at the end of this file restates it). That follow-up is mandatory, not optional.

Provider routing (resolve before execution mode):
- If the active model provider is `openai-codex`, delegate exactly once to an independent runtime-native reviewer or explicit review surface and do not invoke `codex-companion.mjs`. Use Codex's `reviewer` agent, OMP's `/ocr-review` (or independent `task` role with `review-policy.md`), or Pi's `/ocr-review`. Use native background execution when available and consume its completion notification; do not poll a shell session.
- If no independent reviewer or explicit review surface is available, stop and report that review is unavailable. Do not fall back to the companion or self-review.
- Only non-`openai-codex` providers use the companion flows below.

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
- If the user passes their own `--model`, forward it to the selected reviewer when supported; otherwise report that the native reviewer owns model selection.
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

After the review output is available (background completion or foreground return), follow `rules/codex-review-policy.md`:
- Present the findings verbatim, then fix every P0 / P1 / P2 finding in the working tree on the current branch without waiting for the user to choose. Touch only files inside the reviewed diff; never sweep unrelated uncommitted changes into the fix.
- If a P0 cannot be fixed on this branch, stop: no push, no PR. Report it to the user.
- Committing the fixes follows the normal Git rule: confirm with the user unless the current task already delegated commit / PR, and stage the fixed files explicitly (`git add <paths>`). Do not re-run the review afterwards; the PR gate accepts the reviewed commit as an ancestor of HEAD.
- Do not fix P3 or out-of-scope findings; list them as 残件 in the PR body.
- If the output shows the review did not run because of quota / credit exhaustion (usage limit, insufficient quota, rate limit, 429, credit), run `~/.claude/hooks/codex-review-bypass.sh --quota "<one-line error summary>"` (it also records `review.skip` in the Core Workflow when one is active) and write "Codex review: SKIP（quota）" in the PR body. Any other failure (connection, auth, companion crash) stops and asks the user.

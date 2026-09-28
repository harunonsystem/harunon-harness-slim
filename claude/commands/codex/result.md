---
description: Show the stored final output for a finished Codex job in this repository
argument-hint: '[job-id]'
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

Show a finished Codex job's result through the shared built-in companion.

This user-level command overrides the plugin's `/codex:result` so that a finished review is handed to the fix flow in `rules/codex-review-policy.md` instead of the plugin's "stop and ask which issues to fix" default.

Raw slash-command arguments:
`$ARGUMENTS`

Argument safety: the raw arguments are interpolated into a shell command string. Before running, verify every whitespace-separated token consists only of `A-Z a-z 0-9 . _ / @ = -`. If any token contains other characters, do not run the command; tell the user which token was rejected.

Run:
```bash
COMPANION=$(ls -t "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1) && node "$COMPANION" result $ARGUMENTS
```

Present the full command output to the user verbatim. Do not summarize or condense it. Preserve job ID and status, the complete result payload (verdict, summary, findings, details, artifacts, next steps), file paths and line numbers exactly as reported, and any error messages.

If the job is a review, follow `rules/codex-review-policy.md` after presenting: fix every P0 / P1 / P2 finding on the current branch without waiting for the user to choose; list P3 and out-of-scope findings as 残件 for the PR body; do not re-run the review. The plugin's `codex-result-handling` skill says to stop and ask before fixing; that rule does not apply here, the policy above does.

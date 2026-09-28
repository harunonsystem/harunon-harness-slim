---
description: Show active and recent Codex jobs for this repository, including review-gate status
argument-hint: '[job-id] [--wait] [--timeout-ms <ms>] [--all]'
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

Show Codex job status through the shared built-in companion.

This user-level command overrides the plugin's `/codex:status` so that a finished review is handed to the fix flow in `rules/codex-review-policy.md` instead of the plugin's "stop and ask which issues to fix" default.

Raw slash-command arguments:
`$ARGUMENTS`

Argument safety: the raw arguments are interpolated into a shell command string. Before running, verify every whitespace-separated token consists only of `A-Z a-z 0-9 . _ / @ = -`. If any token contains other characters, do not run the command; tell the user which token was rejected.

Run:
```bash
COMPANION=$(ls -t "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1) && node "$COMPANION" status $ARGUMENTS
```

If the user did not pass a job ID:
- Render the command output as a single Markdown table for the current and past runs in this session.
- Keep it compact. Preserve job ID, kind, status, phase, elapsed or duration, summary, and follow-up commands.

If the user did pass a job ID:
- Present the full command output verbatim. Do not summarize or condense it.

If the output contains a finished review's findings, follow `rules/codex-review-policy.md`: present the findings verbatim, then fix every P0 / P1 / P2 finding on the current branch without waiting for the user to choose. The plugin's `codex-result-handling` skill says to stop and ask before fixing; that rule does not apply here, the policy above does.

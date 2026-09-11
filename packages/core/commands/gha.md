---
description: Analyze GitHub Actions failures and identify root causes
argument-hint: <url>
---

Investigate this GitHub Actions URL: $ARGUMENTS

Use the gh CLI to analyze this workflow run.

1. **Check for existing fix PRs first**:
   - `gh pr list --state open --search "<keywords>"` with error messages or file names
   - If a fix PR exists, report it and skip the remaining steps

2. **Get basic info & identify actual failure**:
   - What workflow/job failed, when, and on which commit?
   - Read full logs to find what caused the exit code 1 — distinguish warnings/non-fatal errors from actual failures
   - Look for "failing:", "fatal:", or script logic that triggers exit 1

3. **Check flakiness** (history of the specific failing job, not the whole workflow):
   - `gh run list --workflow=<name>` → `gh run view <id> --json jobs` for the failing job's history across 10-20 runs
   - Success rate, last pass, one-time vs recurring?

4. **Identify breaking commit** (if recurring):
   - Find first failure / last pass boundary, identify the commit, verify the pattern holds

5. **Root cause**: Based on logs, history, and any breaking commit

Write a final report with:
- Summary of failure (what triggered exit code 1)
- Flakiness assessment (one-time vs recurring, success rate)
- Breaking commit (if identified)
- Root cause analysis
- Existing fix PR (if found)
- Recommendation (skip if fix PR exists)

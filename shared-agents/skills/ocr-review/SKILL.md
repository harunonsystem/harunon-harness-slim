---
name: ocr-review
description: Run the Alibaba OpenCodeReview CLI as the canonical diff-review engine.
---

# OCR canonical review

Use this skill when the user asks for a canonical diff review from pi or omp.

This runs only on an explicit request for it. It is the one exception to the runtime's
"route every diff review to the standard reviewer" rule (pi AGENTS.md), so do not reach for
it on your own: an ordinary review request still goes to the runtime's own reviewer.

The review engine is OpenCodeReview CLI (`ocr`), not the runtime's native
reviewer. Keep the review semantics aligned across runtimes by using the same
command shape and by returning the JSON artifact without editing the worktree.

## Review

For current workspace changes, run:

```bash
OCR_ENABLE_TELEMETRY=0 OCR_CONTENT_LOGGING=0 mise exec -- ocr review --audience agent --format json --repo "$PWD"
```

For a branch review, derive the base instead of assuming `origin/main`. A repository whose
default branch is `master` or `develop` would otherwise fail or diff against the wrong ref,
and an un-fetched `origin/main` produces findings from a stale baseline.

```bash
git fetch origin --quiet
BASE=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD || echo origin/main)
MERGE_BASE=$(git merge-base "$BASE" HEAD)
OCR_ENABLE_TELEMETRY=0 OCR_CONTENT_LOGGING=0 mise exec -- ocr review --audience agent --format json --repo "$PWD" --from "$MERGE_BASE" --to HEAD
```

If the user names a base branch, use theirs instead of the derived one. Confirm the resolved
base in the report so the reader can tell what the findings were diffed against.

The command is read-only with respect to the worktree. Do not apply fixes,
commit, or start another review in the same task. Report the JSON findings with
file and line locations, severity, and the review session or artifact path.

Before an LLM request, preview the selected files when the scope is unclear:

```bash
OCR_ENABLE_TELEMETRY=0 OCR_CONTENT_LOGGING=0 mise exec -- ocr review --audience agent --preview --repo "$PWD"
```

If OCR is not configured with an LLM, report that configuration is required;
do not silently switch to a different provider or a runtime-native reviewer.

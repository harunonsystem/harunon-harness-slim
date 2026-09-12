---
name: run-change
description: Start, resume, and advance the shared harunon-harness Core Workflow from any supported coding agent.
compatibility: codex opencode pi omp claude
---

# Run Change

Use the runtime-neutral Core Workflow instead of recreating the development process in the prompt.

## Native Interface First

- OpenCode: use the `harness_workflow` custom tool. State is per git worktree, so when the task lives in a worktree other than the session directory, pass that worktree as `cwd` on every call (the same `cwd` you give the bash tool).
- Codex: use this skill's `scripts/harness.py`; keep review inside the active Codex runtime.
- Claude / pi / omp and other runtimes: use `scripts/harness.py`. Runtime adapters translate native tool events to the same policy actions.

Do not edit state files directly. Every mutation uses revision compare-and-swap and schema validation.

## Path Layout

- Source repository: `packages/core/policy/harnessctl.py` and `packages/core/workflows/change.json`.
- Installed runtime: `policy/harnessctl.py` and `workflows/change.json`, relative to the runtime config directory—not the current project repository.
- Agents invoke the kernel through this skill's `scripts/harness.py`; do not run `policy/harnessctl.py` relative to the project root.

## Resume

Inspect first:

```bash
python3 <skill-dir>/scripts/harness.py status
```

If the result is `STATE_NOT_FOUND`, start the task. A previous task that never left `intake` (revision 0) is replaced by `start`; a task with recorded progress returns `ACTIVE_TASK_EXISTS` and must be finished in its own worktree first:

```bash
python3 <skill-dir>/scripts/harness.py start <task-id>
```

For a branch that is already implemented, checked, committed, and pushed, enter the publish-only path instead of replaying the change phases:

```bash
python3 <skill-dir>/scripts/harness.py start <task-id> --publish-only
```

## Advance

Read the current `revision` from status and apply exactly one valid event:

```bash
python3 <skill-dir>/scripts/harness.py advance <event> --revision <revision>
```

The shared flow is:

```text
intake -> clarify? -> isolate -> plan -> implement -> verify
-> checkpoint -> review -> decide -> publish -> complete
```

An invalid transition or stale revision must remain blocked. Re-inspect instead of retrying with guessed state.

## Review

At `review`, use the runtime's built-in reviewer. In Codex, use the active runtime's reviewer with the configured `review_model`; when the reviewer subagent is available, spawn the `reviewer` agent. Do not shell out to `codex review` and do not use a plugin process to start another Codex session.

Save the reviewer's complete final output as a temporary artifact, then attach it explicitly:

```bash
python3 <skill-dir>/scripts/harness.py attach-review \
  --revision <revision> --provider codex --subject-sha "$(git rev-parse HEAD)" \
  --artifact <review-output-file>
```

The kernel refuses a missing artifact, a stale HEAD, an invalid phase, or an unapproved second review. Local evidence is explicitly `audit-only`: it prevents accidental PR creation but is not a security boundary.

After the findings are presented, fix every P0 / P1 / P2 on the branch and record `findings_fixed` with `advance` (no second review; the PR gate accepts the reviewed commit as an ancestor of HEAD). P3 and out-of-scope findings go to the PR body as 残件. Use `accepted` when there is nothing to fix, `findings_deferred` when the user explicitly defers, and `fix_selected` only when the user asks for a fix loop with a second review.

If the reviewer did not return because of quota / credit exhaustion, record the skip instead of an attach and move on to publish; the PR body must say the review was skipped:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider codex --reason "<reviewer error summary>"
```

Any other reviewer failure (connection, auth, crash) is not a skip: stop and ask the user.

A second review is blocked until the user explicitly approves it. Record that approval and its reason before invoking the adapter again:

```bash
python3 <skill-dir>/scripts/harness.py approve-review --revision <revision> --reason "<user-approved reason>"
```

## Publish

Before PR creation, authorize the normalized action. In Codex, prefer the GitHub app's pull-request tool when it is available; use `gh` only as a fallback.

```bash
python3 <skill-dir>/scripts/harness.py authorize pr.create
```

Runtime gates only apply while a task has recorded progress. `STATE_NOT_FOUND` (never started) and `WORKFLOW_INACTIVE` (previous task `complete`, or still at `intake` with revision 0) are not blocks; the gate falls back to the runtime's default PR policy. Start a new task with `start` if you want the workflow to govern the change.

An explicit user request to create the PR is the publication confirmation. Do not ask for the same confirmation again; only surface a platform permission prompt when the runtime itself requires one.

PR merge remains subject to the external required status check and branch rules. Never treat writable local state as merge authorization.

## Assignments

At `implement` or `review`, a coordinator can delegate the phase to a worker executor instead of doing it inline. Only one assignment is live at a time; create the next one only after the current one is `reported` or `abandoned`.

```bash
python3 <skill-dir>/scripts/harness.py assign implement --executor codex --worker-id <session-id> --revision <revision>
python3 <skill-dir>/scripts/harness.py dispatched --transport agmsg --ref '{"team":"...","to":"..."}' --at "$(date -u +%FT%TZ)" --revision <revision>
python3 <skill-dir>/scripts/harness.py report --executor codex --worker-id <session-id> --result-sha "$(git rev-parse HEAD)" --artifact <report-file> --checks '[{"command":"pytest","exitCode":0}]' --revision <revision>
python3 <skill-dir>/scripts/harness.py abandon --reason "<why the worker was abandoned>" --revision <revision>
```

`assign` returns a `correlationId` in the state's last assignment; embed it in the dispatch message so the worker's reply can be matched back to this assignment. `report` verifies the worker actually advanced past the assigned base (`resultSha` must be `HEAD`, and the assignment's base must be its ancestor) before marking the assignment `reported`. `phase.advance implemented` is blocked until an `implement` assignment is `reported`; a review assignment reports through this same command or through `attach-review`, whichever is already in flight.

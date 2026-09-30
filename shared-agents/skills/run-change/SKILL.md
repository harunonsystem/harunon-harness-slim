---
name: run-change
description: Start, resume, and advance the shared harunon-harness Core Workflow from any supported coding agent.
compatibility: codex opencode pi omp claude
---

# Run Change

Use the runtime-neutral Core Workflow instead of recreating the development process in the prompt.

`run-change` owns lifecycle state, policy gates, and evidence binding. It does **not** own worker selection, spawning, dispatch, retries, worktree management, or runtime-specific handoff. Those belong to each runtime's native orchestration layer.

## Native Interface First

- OpenCode: use the `harness_workflow` custom tool. State is per git worktree, so when the task lives in a worktree other than the session directory, pass that worktree as `cwd` on every call (the same `cwd` you give the bash tool).
- Codex: use this skill's `scripts/harness.py`; keep review inside the active Codex runtime.
- Claude / pi / omp and other runtimes: use `scripts/harness.py`. Runtime adapters translate native tool events to the same policy actions.
- When phase work is delegated, use the runtime-native execution surface instead of building another coordinator inside `run-change`. Runtime-specific package or tool selection belongs to the target adapter/instructions, not this shared skill.

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

When an intake skill such as `implement-issue` has already resolved the task and created the worktree, use the native interface from that worktree. Reuse its task ID, acceptance criteria, and verification commands; record completed intake/isolation as phase transitions without fetching the issue or creating another worktree. Keep the task details in the runtime's context; the kernel stores lifecycle state and evidence, not a second task brief.

For a branch that is already implemented, checked, and committed, enter the publish-only path instead of replaying the change phases:

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

## Verify

Run deterministic project checks first (tests, typecheck, lint, build, or the repository's declared verification commands). They remain the source of truth for `checks_passed`.

When the shared Jev MCP is available and the change is non-trivial, use `jev_verify` as an advisory evidence check over the task/completion claims, relevant diff or artifacts, and the deterministic check results. Treat its typed judgment as a signal only: it may request more evidence or surface a mismatch, but it never substitutes for executable checks and must not advance or block the Core Workflow by itself. If Jev is unavailable, continue with deterministic verification; do not fail the task solely because the advisory evaluator is missing.

## Review

Before push or PR creation, run `pre-review-check` over the whole branch diff, not just the last commit. Resolve its critical and major findings and run the required deterministic checks. `BLOCKED` or `INCOMPLETE` is not publication-ready. Save the complete `PASSED` report, including the base/head, findings, check results, and unavailable optional checks, as a temporary artifact.

The default evidence is this self-check, not an independent external review. Attach the actual report explicitly:

```bash
python3 <skill-dir>/scripts/harness.py attach-review \
  --revision <revision> --provider self-check --subject-sha "$(git rev-parse HEAD)" \
  --artifact <self-check-report-file>
```

The kernel refuses a missing artifact, a stale HEAD, an invalid phase, or an unapproved second attachment. Local evidence is explicitly `audit-only`: it prevents accidental PR creation but is not a security boundary. The agent must verify the report's `PASSED` status; the kernel does not interpret its findings. Use `advance accepted` to reach `publish`. Never describe this evidence as an independent review or use it to authorize a merge.

Invoke an independent reviewer only when the user explicitly requests one. In Codex, use the active runtime's reviewer with the configured `review_model`; when the reviewer subagent is available, spawn the `reviewer` agent. Other runtimes must use an available independent review surface. Do not shell out to `codex review` and do not use a plugin process to start another Codex session. Follow `rules/codex-review-policy.md`, save the complete reviewer output, and attach it with the actual provider instead of `self-check`.

After the findings are presented, fix every P0 / P1 / P2 on the branch and record `findings_fixed` with `advance` (no second review; the PR gate accepts the reviewed commit as an ancestor of HEAD). P3 and out-of-scope findings go to the PR body as 残件. Use `accepted` when there is nothing to fix, `findings_deferred` when the user explicitly defers, and `fix_selected` only when the user asks for a fix loop with a second review.

If an explicitly requested reviewer did not return because of quota / credit exhaustion, record the skip instead of an attach only after the mandatory self-check has passed; the PR body must say the external review was skipped:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider <provider> --reason "<reviewer error summary>"
```

Any other reviewer failure (connection, auth, crash) is not a skip: stop and ask the user.

A second review is blocked until the user explicitly approves it. Record that approval and its reason before invoking the adapter again:

```bash
python3 <skill-dir>/scripts/harness.py approve-review --revision <revision> --reason "<user-approved reason>"
```

## Publish

Before drafting the PR body, read `rules/pr-body.md`. If the repository has `.github/PULL_REQUEST_TEMPLATE.md`, preserve its headings and checklists while applying the readability rules inside each section.

Before PR creation, authorize the normalized action. In Codex, prefer the GitHub app's pull-request tool when it is available; use `gh` only as a fallback.

```bash
python3 <skill-dir>/scripts/harness.py authorize pr.create
```

Runtime gates only apply while a task has recorded progress. `STATE_NOT_FOUND` (never started) and `WORKFLOW_INACTIVE` (previous task `complete`, or still at `intake` with revision 0) fall back to legacy runtime gates; they do not waive the mandatory self-check. Before publishing without an active task, use `start --publish-only`, perform the self-check, and attach its report rather than creating legacy bypass flags.

An explicit user request to create the PR is the publication confirmation. Do not ask for the same confirmation again; only surface a platform permission prompt when the runtime itself requires one.

PR merge remains subject to the external required status check and branch rules. Never treat writable local state as merge authorization.

## Delegation Boundary

At `implement` or `review`, execution may be delegated, but orchestration stays outside `run-change`.

- Runtime-native orchestration owns worker selection, spawn/dispatch, retries, worktree mechanics, and worker-to-reviewer handoff.
- `run-change` records only lifecycle transitions and the evidence needed by policy gates.
- The runtime-specific parent/coordinator supplies scope / acceptance criteria / deterministic check commands, then validates the resulting diff and checks before advancing the Core Workflow. Do not mirror the runtime's worker lifecycle as a second manual `assign -> dispatched -> report` loop.
- The kernel's `assignment.create`, `assignment.dispatched`, `assignment.report`, and `assignment.abandon` operations remain low-level compatibility/provenance APIs for adapters that need an auditable external-worker record. They record facts; they are not the default orchestration API.
- A runtime may delegate without creating a kernel assignment. Existing gates only require a report when an assignment was explicitly created, so inline and runtime-native delegation remain valid.

Keep one source of truth per concern: Core Workflow for lifecycle/policy/evidence, runtime-native orchestration for execution.

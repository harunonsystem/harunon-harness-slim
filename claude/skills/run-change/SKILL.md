---
name: run-change
description: Bind verification and publication evidence, or resume an existing Core Workflow.
compatibility: codex opencode pi omp claude
---

# Run Change

When `yomiyasu` is unavailable, proofread the wording locally under the same constraints instead of invoking it.

Follow the resident Routing instructions for implementation, directly or through the selected pstack skill; keep the runtime's native execution loop. This skill uses the common kernel for required outcomes, verification evidence, and completion/publication gates, and resumes existing Core Workflow state; it does not orchestrate implementation. For a new task, finish the work and checks, then use `start --publish-only` before publishing. If a task already has active state, resume it and record completed phases without replaying work.

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
- State: `<absolute-git-dir>/harness/v2/state.json`, with receipts alongside it. The legacy `harness/state.json` is not migrated or edited.
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

For work already performed by a native loop, enter the gate path instead of replaying its planning or implementation. This entry works for uncommitted changes too; it does not publish anything:

```bash
python3 <skill-dir>/scripts/harness.py start <task-id> --publish-only
```

## Advance

Read the current `revision` from status and apply exactly one valid event:

```bash
python3 <skill-dir>/scripts/harness.py advance <event> --revision <revision>
```

The compatibility lifecycle is below; do not replay it as a mandatory native execution procedure:

```text
intake -> clarify? -> isolate -> plan -> implement -> verify
-> checkpoint -> review -> decide -> publish -> complete
```

An invalid transition or stale revision must remain blocked. Re-inspect instead of retrying with guessed state.

## Verify

The repository owns `.harness/verification.json`: a non-empty `commands` array of argv arrays referencing its existing mise tasks, package scripts, or verification scripts. A repository without the file in its working tree, `HEAD`, or origin default branch has not adopted the gates: completion and publication are not gated there, so do not create the file in other projects. Invalid or empty declarations are unverified; ask the repository owner to establish the mandatory checks instead of substituting optional tests or an agent's success claim. Full declaration and evidence contract: `policy/verification.md` under the runtime config directory.

Read status, then run the mandatory checks through the kernel:

```bash
python3 <skill-dir>/scripts/harness.py verify --revision <revision>
```

OpenCode uses `harness_workflow` operation `verify` with `arguments.expectedRevision`. The kernel executes every declared command, records exit codes/logs and the checkout fingerprint, and advances `verify` only on success. Manual `checks_passed` is protected. Additional native checks are useful but cannot replace this evidence.

Use the returned revision; verification records both the attempt and its result. Failure, timeout, interruption, changed inputs, or altered/missing evidence blocks completion/publication. Rerun after any checkout, declaration, or HEAD change, including a commit or review fix.

`start --publish-only` enters `review`. A successful `verify` there (or at `checkpoint`, `decide`, `publish`, `complete`) keeps that phase. In the normal `verify` phase it advances to `checkpoint`; use `advance review_ready --revision <returned-revision>` to enter `review` without committing. Existing `committed` remains a compatibility event, not permission to commit.

## Complete without publication

After the native loop has met the requested outcomes, attach the mandatory self-check below and advance its decision to `publish`. This phase is only gate-ready; no PR is required. With mandatory verification current, read status and record completion:

```bash
python3 <skill-dir>/scripts/harness.py complete --revision <revision>
```

In Claude, Codex, omp, and pi, a turn-end hook checks any completion claim against the kernel (`task.report`: phase `complete` with current verification) and sends the turn back once if it fails. If the work is not complete, say so instead of claiming it.

OpenCode uses operation `complete`. This only completes the local task; it grants no permission to commit, push, create a PR, merge, or deploy. Completion is blocked without current kernel verification and the existing local self-check/review gate. A completed task never bypasses publication approval or evidence freshness.

## Review

Before completion, push or PR creation, run `pre-review-check` over the whole branch diff, not just the last commit. Resolve its critical and major findings and run the required deterministic checks. `BLOCKED` or `INCOMPLETE` is not completion/publication-ready. Save the complete `PASSED` report, including the base/head, findings, check results, and unavailable optional checks, as a temporary artifact.

The default evidence is this self-check, not an independent external review. Attach the actual report explicitly:

```bash
python3 <skill-dir>/scripts/harness.py attach-review \
  --revision <revision> --provider self-check --subject-sha "$(git rev-parse HEAD)" \
  --artifact <self-check-report-file>
```

The kernel refuses a missing artifact, a stale HEAD, an invalid phase, or an unapproved second attachment. Local evidence is explicitly `audit-only`: it prevents accidental PR creation but is not a security boundary. The agent must verify the report's `PASSED` status; the kernel does not interpret its findings. Use `advance accepted` to reach `publish`. Never describe this evidence as an independent review or use it to authorize a merge.

Pstack design critics and internal review panels run within the authorized implementation scope; their findings do not replace the mandatory publication self-check or authorize publishing. Invoke a separate external review service only when the user explicitly requests one. In Codex, use the active runtime's reviewer with the configured `review_model`; when the reviewer subagent is available, spawn the `reviewer` agent. Other runtimes must use an available independent review surface. Do not shell out to `codex review` and do not use a plugin process to start another Codex session. Follow `rules/codex-review-policy.md`, save the complete reviewer output, and attach it with the actual provider instead of `self-check`.

After the findings are presented, fix every P0 / P1 / P2 on the branch and record `findings_fixed` with `advance` (no second review; the PR gate accepts the reviewed commit as an ancestor of HEAD). P3 and out-of-scope findings go to the PR body as 残件. Use `accepted` when there is nothing to fix, `findings_deferred` when the user explicitly defers, and `fix_selected` only when the user asks for a fix loop with a second review.

If an explicitly requested reviewer did not return because of quota / credit exhaustion, record the skip instead of an attach only after the mandatory self-check has passed; the PR body must say the external review was skipped:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider <provider> --reason "<reviewer error summary>"
```

Any other reviewer failure (connection, auth, crash) is not a skip: stop and ask the user.

The skip alone does not satisfy completion/publication. After recording it, attach the already-passed self-check report with `--provider self-check`, then `advance accepted`; the kernel accepts that attachment from the quota-skipped `publish` phase.

A second review is blocked until the user explicitly approves it. Record that approval and its reason before invoking the adapter again:

```bash
python3 <skill-dir>/scripts/harness.py approve-review --revision <revision> --reason "<user-approved reason>"
```

### GitHub review replies and resolution

For the two approved namespaces, follow `rules/review-policy.md` and the managed
`policy/comment-owner-policy.md` subset. Approved-owner repository visibility is not
an authorization condition. Before resolving, read the actual finding
and thread, inspect the fix at the current GitHub PR head, and record its verification
and finding ID in the real review/fix evidence. Only resolve findings actually fixed;
outdated status, a changed file, a reply, a receipt, or a hash alone is not that judgment.
The helper binds owner/repo/PR/thread/head/operation, not semantic correctness.
Local review evidence remains audit-only and never grants native/platform consent.
Other/unknown owners and unsupported connectors retain DENY/ASK; stop on independent
native refusal without another command shape or connector.

## Publish

Before drafting the PR body, read `rules/pr-body.md`. If the repository has `.github/PULL_REQUEST_TEMPLATE.md`, preserve its headings and checklists while applying the readability rules inside each section. After the structure, facts, evidence, and risk statements are fixed, run the final Japanese prose through `yomiyasu --domain business` before publication. Treat `yomiyasu` as a wording-only pass: it must not invent, remove, or strengthen technical claims, evidence, risk, or unresolved findings.

Before PR creation, authorize the normalized action. In Codex, prefer the GitHub app's pull-request tool when it is available; use `gh` only as a fallback.

```bash
python3 <skill-dir>/scripts/harness.py authorize pr.create
```

In a repository that has adopted the gates, missing tasks and stale workflow versions return `TASK_REQUIRED`: use `start --publish-only`, kernel verification, and the passed self-check before publishing. An untouched `intake` task must enter the gates; a completed task still requires current verification and local review evidence. Legacy flags and inactive-task status never substitute for either requirement.

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

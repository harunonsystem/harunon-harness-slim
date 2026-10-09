# Core Workflow verification contract

The harness owns the declarations in `policy/verification-repos.json`, distributed from the SSOT; repositories carry no harness file. Entries are keyed by remote identity (`host/owner/repo`, lowercased for GitHub; `*` applies to every repository). Commands are argv arrays, not shell strings; use an explicit shell command only when the existing entrypoint needs globbing or pipelines.

```json
{
  "github.com/owner/repo": {
    "timeoutSeconds": 1800,
    "commands": [["mise", "run", "test"], ["npm", "run", "lint"]]
  }
}
```

A repository adopts the gates when any of its remote URLs canonicalizes to a registered identity; tracked files cannot un-adopt it, but the remote URL in `.git/config` is the identity (outside the receipt threat model below). An unreadable registry counts as adopted and blocks. `HARNESS_VERIFICATION_REPOS` overrides the registry path. Elsewhere `authorize` returns `NOT_ADOPTED` (allowed) for every action. The declaration must contain at least one command. Timeout applies per command, defaults to 1800 seconds, and must be an integer between 1 and 86400. Each check executes at the repository root with inherited environment, no interactive stdin, and a combined stdout/stderr log. Timeout kills its process group. The kernel executes the declaration; callers cannot select, omit, or replace commands.

State and receipts are worktree-local in `<absolute-git-dir>/harness/v2/`. Verification binds HEAD, index, tracked/untracked file contents and modes, initialized submodules, and declaration hash. Ignored outputs, tool binaries, environment variables and external services are outside this fingerprint: this is not a reproducible-build guarantee.

A failed or interrupted rerun revokes earlier success. A successful receipt and its logs must still exist with their recorded hashes, every mandatory command must have exited zero, and inputs must still match. Reverify after edits, commits, or declaration changes. Receipts are kernel-generated `audit-only` evidence, not a security boundary against another process with the same filesystem privileges.

`verify` and `complete` use revision compare-and-swap. Verification persists a pending unsuccessful attempt before spawning commands, then persists the result; always use the returned revision or inspect after interruption. Completion and publication both require current mandatory verification and the existing local self-check/review gate. Completion must be gate-ready (`publish` or already `complete`), not an early lifecycle exit. Merge still requires external trusted checks and branch protections. In an adopted repository, a missing task is blocked, including the publish-only route.

Native execution loops choose planning, worker tools, retries and order. `run-change` only exposes the common lifecycle/evidence contract. For already implemented work, `start --publish-only` enters its gates without replaying native planning.

An external review quota skip is not a self-check artifact. Record the skip, attach the passed self-check with provider `self-check`, and accept its decision before completion/publication. The skip remains audit evidence and does not require rerunning the external reviewer.

Only recognized publication commands/tool events are mechanically gated. In Claude, Codex, omp, and pi, a turn-end hook also checks regex-detected completion claims against `task.report` (phase `complete` with current verification) and sends the turn back once. Rephrased claims, a second stop in the same turn, dynamic shell dispatch, manually invoked API clients, disabled runtime hooks, and runtimes without a turn-end hook are not a sandbox: agents must record completion through the kernel before reporting the task as finished.

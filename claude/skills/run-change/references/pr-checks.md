# Wait for PR checks without streaming logs

Use this when the task calls for waiting after a push or PR creation. Confirm that the PR is open and its head matches the published SHA (see **Resume and handoff** in [run-change](../SKILL.md)).

1. On runtimes that keep a command running after the tool call returns (background task or detached shell), start one background command with a 30-minute tool timeout. Let the CLI poll and keep its progress in a local file. Keep the log path when dispatching (the watcher should print only that path before waiting).

   ```bash
   watch_log="$(mktemp)" || exit 1
   printf 'watch log: %s\n' "$watch_log"
   gh pr checks "$pr" --repo "$repo" --watch --interval 30 >"$watch_log" 2>&1
   ```

   On runtimes whose shell tool returns only after the command exits — standard Pi, which retired `interactive_shell` — do not use the background form. Run the watch in the foreground with a bounded tool `timeout` instead:

   ```bash
   gh pr checks "$pr" --repo "$repo" --watch --interval 30
   ```

2. Once all checks finish, read the counts and failing check links in one tool call. Keep the `bucket` fields: the completion hook reads this JSON array as CI evidence.

   ```bash
   gh pr checks "$pr" --repo "$repo" --json name,bucket,link \
     --jq '[group_by(.bucket)[] | if .[0].bucket == "fail" or .[0].bucket == "cancel" then .[] else {bucket: .[0].bucket, count: length} end]'
   ```

3. Recheck the PR head in a **separate tool call** so its JSON does not mix with the check summary.

   ```bash
   gh pr view "$pr" --repo "$repo" --json headRefOid,state
   ```

   If the head changed, discard the result and reconcile. If the PR is no longer open, report its state and stop.

Empty checks, pending checks, a timeout, or an API error are not success. If checks have not appeared yet, retry the bounded watch once instead of polling from the model. Inspect `$watch_log` only to diagnose a watch error. For a failing Actions job, read only `gh run view <run-id> --job <job-id> --log-failed`. Delete the temporary log after use. The summary is not merge authorization.

## Optional: GitHub event subscriptions

If the account already has access to the preview, [`gh event listen`](https://cli.github.com/manual/gh_event_listen) with `com.github.pull_request.check_suite.status.changed.v1` can wake the background command. One event covers one suite, not the whole PR. Check current state after attaching or reconnecting and after a signal; earlier events are not replayed. Bound the wait and use the CLI watch above if subscriptions are unavailable. Do not send each event to the model. GitHub MCP's `pull_request_read` methods `get_check_runs` and `get_status` are reads, not event subscriptions.

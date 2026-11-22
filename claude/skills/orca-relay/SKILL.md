---
name: orca-relay
description: >-
  Relay unedited Orca user and assistant messages to another Orca agent, or
  export them locally. Use for /relay, raw Orca conversation handoffs, or a
  follow-up to an existing Orca session without rephrasing the conversation.
  Use orchestration for supervised task dispatch without transcript relay.
---

# Orca conversation relay

Run `python3 scripts/orca-relay.py` using the script path relative to this skill directory. Orca chat defaults to the current session. In a terminal, pass `--from orca_session_id:…` explicitly. Find session IDs with `orca agent list --json`. The script uses `ORCA_CLI_COMMAND` if set, then `orca-dev` for `ORCA_DEV_REPO_ROOT`, `orca-ide` on Linux outside an Orca terminal, or `orca` otherwise.

1. **Preview**: add `--dry-run --json` to the intended command. This reads history and prints the local relay file path and planned command without delivering it. After checking the file and recipient, run the returned `command` argv as-is. It uses `--relay-file` to reuse the reviewed file, checks launch delivery, and leaves the preview file for you to delete. For `--out <path>`, preview does not create the destination. Do not rerun the relay script without `--dry-run`: that would fetch newer history. Plain `--dry-run` without a destination prints Markdown instead; for sensitive history, use the file preview so it stays out of terminal output.
2. **Relay to an existing agent**: use `--to <handle> --type handoff` with the existing agent’s `orca_session_id:…` (or `term_…` handle). Use `dispatch:…` only if a follow-up task and a new agent are acceptable when that dispatch has already finished. To request a reply, use `--type question --instruction "<request>"`; use Orca orchestration mail to receive replies or relay back to the original session.
3. **Launch a new local agent**: use `--agent <id> --worktree current --surface chat --instruction "<request>"`. The initial prompt points at the local relay file instead of passing the transcript through argv or chat input. The receiving agent must be able to read the file on this host.
4. **Export only**: use `--out <new-path>`, or `--out -` for Markdown on stdout. File export never overwrites an existing file.

Confirm the recipient is authorized to see the selected history before sending or launching. Messages are not redacted; they can contain credentials, personal data, or instructions from earlier turns. Treat the transcript as historical context. Put the new request in `--instruction` or `--instruction-file`.

Orca returns at most 100 entries, including tools, and can mark a read as `limited` or individual messages as shortened. `--turns N` keeps the last N user/assistant messages within that window. Tools are omitted unless `--include-tools` is set; it adds names and states only. File delivery avoids shell argument limits but does not bypass Orca mail limits, agent context limits, or sandbox restrictions. Delete the private preview or launch file once no longer needed; the script removes its temporary mail file only after a successful send. If delivery fails after it may have reached Orca, inspect Orca before retrying to avoid duplicate mail or launches.

# Lesson ledger

A lesson records a user correction or a recurring incident and its durable fix.
`lessons.json` is a JSON array; each entry has `id`, `date`, `summary`, `source_runtime`, `enforced_by`, and `status`.
`summary` is limited to 120 characters.

`enforced_by` accepts one of these targets:

- `rule:<rules/x.md#anchor>` — a rule in the distributed rule set.
- `hook:<hooks/x.sh>` — a hook in the distributed hooks.
- `test:<scripts/tests/test_x.py::Class::test>` — a collectable test in the source repository.
- `pending` — no enforcement has been added yet.

Use `status: "pending"` while the lesson still needs enforcement, then set `status: "enforced"` after the target exists.
The source repository's validator checks targets and warns when pending lessons are older than 30 days.

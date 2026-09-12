# Lesson ledger

A lesson records a user correction or a recurring incident and its durable fix.
`lessons.json` is a JSON array; each entry has `id`, `date`, `summary`, `source_runtime`, `enforced_by`, and `status`.
`summary` is limited to 120 characters.

`enforced_by` accepts one of these targets:

- `rule:<rules/x.md#anchor>` — a rule under `packages/core/`.
- `hook:<hooks/x.sh>` — a hook under `packages/core/`.
- `test:<scripts/tests/test_x.py::Class::test>` — a collectable unittest.
- `pending` — no enforcement has been added yet.

Use `status: "pending"` while the lesson still needs enforcement, then set `status: "enforced"` after the target exists.
`validate-harness.py` checks targets and warns when pending lessons are older than 30 days.

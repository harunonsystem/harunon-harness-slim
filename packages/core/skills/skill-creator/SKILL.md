---
name: skill-creator
description: Design a new skill or revise an existing skill's workflow, trigger boundaries, resources, or packaging. Use writing-for-agents for wording-only changes and skill-improvement for behavioral evaluation.
license: Complete terms in LICENSE.txt
---

# Skill creator

Build a skill around a repeatable task that the agent needs help performing. Keep the user's scope and existing authorization intact.

## Inspect and choose the scope

1. Read the closest existing skill, its callers and bundled resources. Reuse or extend it when it already owns the capability.
2. Define the requests the skill should handle and any likely neighboring task it should leave alone. Ask only for information that cannot be inferred from the request or existing artifacts.
3. Before editing, fix a representative task, an edge case and an unused hold-out. Include at least one critical correctness requirement. For trigger changes, include a positive and a negative prompt.
4. Check ownership. In Harness, edit core or extras SSOT. Rulesync-managed upstream skills remain unchanged; their updates come from rulesync.

## Structure the skill

Keep purpose, shared steps, essential constraints, completion criteria and resource-loading conditions in `SKILL.md`.
Put substantial mode-specific procedures, examples and schemas in `references/`, executable helpers in `scripts/`, and output resources in `assets/`.
A short self-contained skill needs no extra directories.

Use relative links from `SKILL.md` and state when each file is needed. Read only relevant references; moving content out and then loading every file does not reduce context use.
Keep each instruction in one authoritative place. Link to existing policies instead of copying their full checklists.

- Multiple modes or complex resource layout: read [resource-patterns](references/resource-patterns.md).
- Sequential or conditional workflow design: read [workflows](references/workflows.md).
- Output format or examples: read [output-patterns](references/output-patterns.md).
- Wording, pointers or hierarchy: use `writing-for-agents`.

Aim below 500 lines and about 5,000 tokens for the entrypoint; these are upper guidelines, not targets. Metadata loads during discovery, so keep the description short and discriminating. Bytes and words are not token counts.

## Write the workflow

Include task-specific guidance that changes decisions: fragile operations, known boundary conditions, required inputs and how to verify the result.
Use a fixed sequence when order affects correctness. For flexible work, describe the outcome and selection criteria.
Avoid generic tutorials, forced interviews, repeated safety text and speculative edge cases.
Preserve supported metadata and existing invocation policy when updating a skill.

Frontmatter needs a nonempty `name` and `description`. Standard optional fields include `license`, `compatibility`, `metadata` and experimental `allowed-tools`.
Claude also supports fields such as `disable-model-invocation`, `user-invocable`, `argument-hint`, `context`, `agent`, `model` and `hooks`.
Runtime-specific fields do not imply the same behavior on other hosts. In Harness, inspect the target's frontmatter transform and disabled-skills declarations before claiming cross-runtime support.
Keep tool-specific requirements in compatible targets or express the necessary outcome in portable prose.

For a new standalone skill, use the bundled initializer when appropriate:

```bash
python3 scripts/init_skill.py <skill-name> --path <destination>
```

Resolve the script path from this skill directory. Inspect the generated files, keep resources that the task needs, and remove scaffolding with the user's existing authorization.
For an existing skill, edit its files directly rather than rerunning the initializer.
For a repository with its own layout and distribution scripts, copy the closest local implementation instead.

## Validate and evaluate

Run changed executable helpers against realistic inputs. Use the project's tests and distribution checks when available.
For standalone frontmatter validation:

```bash
python3 scripts/quick_validate.py <skill-directory>
```

This is a basic syntax/name/field check; it does not validate every reference or prove behavioral quality.
Open the referenced resources to verify paths and loading conditions. Confirm that mandatory inputs, outcomes and stopping conditions are reachable from the entrypoint.

Use `skill-improvement` for the baseline, fresh scenario runs and hold-out when workflow, triggers, reference routing or agent decisions change. Pass raw task inputs to evaluators and keep expected answers out of their prompts. Report failed or unavailable evaluations separately from completed checks.

## Deliver

Use the repository's distribution mechanism for repository-managed skills. Harness distributes skill directories through target manifests; a `.skill` archive is unnecessary for that workflow.
Only when the user needs an archive, run:

```bash
python3 scripts/package_skill.py <skill-directory> [output-directory]
```

The packager validates frontmatter and writes a ZIP-compatible `.skill` file. Inspect the archive before sharing it; packaging does not verify the workflow or grant publication approval.

Report the changed behavior, validation and remaining limitations. Retain license and attribution files.

References: [Agent Skills specification](https://agentskills.io/specification), [skill creation best practices](https://agentskills.io/skill-creation/best-practices).

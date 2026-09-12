# Routing and context policy

Use this reference when changing a skill description, trigger boundary, context-loading rule, or runtime-specific instruction strategy.

## 1. Metadata is for selection

Frontmatter is paid before the skill body is selected, so keep it compact and discriminating.

A good description answers two questions:

- What concrete task should select this skill?
- What nearby task should not select it?

Do not put workflow steps, generic quality guidance, long example lists, or implementation detail in metadata. If a description must enumerate many unrelated triggers, the skill probably owns too much surface area.

## 2. Load context conditionally

The entrypoint should be sufficient to choose the active path. Put large procedures, examples, schemas, and rare edge cases in references and state the condition for opening each one.

Prefer:

- read `references/foo.md` when the task is in foo mode
- inspect the architecture document when changing a subsystem boundary
- load examples only when the requested output shape is ambiguous

Avoid:

- read every reference before starting
- always preload architecture, database, API, and style documents
- invoke sibling skills only to obtain generic guidance

Moving text to a reference does not save context if every invocation still reads it.

## 3. Specify boundaries, not ceremony

Use mandatory sequencing only where order protects correctness. Otherwise specify constraints, decision criteria, and the observable end state.

Prefer a completion boundary such as:

- implementation exists
- required verification has run
- failures introduced by the change are fixed or explicitly reported
- the requested artifact/result is delivered

Avoid forcing confirmation checkpoints, repeated rereads, or fixed intermediate narration unless the task genuinely requires them.

## 4. Keep model/runtime policy evidence-based

Do not fork a skill or add target-specific scaffolding merely because a new model exists. Start from the portable skill behavior.

Add runtime/model-specific policy only when at least one of these is true:

- the runtime exposes a different capability or metadata contract
- an observed behavior repeatedly violates the portable completion boundary
- a host-specific safety or tool constraint requires different instructions

Keep such policy in the relevant target layer so the shared skill remains portable. Remove obsolete compensating instructions when the underlying behavior no longer needs them.

## 5. Evaluate routing changes as routing changes

For a changed description or trigger boundary, test at minimum:

- one positive task that must select the skill
- one nearest-neighbor negative task that must not select it
- one realistic edge case

For changed context routing, verify that the active path can reach every required resource and that unrelated references are not mandatory.

For changed completion semantics, verify the task can finish without an unnecessary confirmation loop and still produces evidence for required checks.

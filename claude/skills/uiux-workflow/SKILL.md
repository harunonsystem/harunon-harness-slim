---
name: uiux-workflow
description: Choose design, Figma implementation, prototype, and UI review tools for the requested frontend scope.
user-invocable: true
---

# UI/UX workflow

Coordinate the design and review tools without replacing their specialist work.

## Tool roles

- `baoyu-design`: explore directions, create prototypes, import Figma/HTML/GitHub context, and author or preview a design system. This is an optional external skill.
- `impeccable-preflight`: run Impeccable's pinned deterministic detector against the implemented UI before subjective review. It catches machine-detectable anti-patterns and quality issues; its findings are candidates to verify, not design truth.
- `better-interface`: review the implemented interface across UI polish, typography, colour, layout, writing, and accessibility. This is an external skill from `jakubkrehel/skills`, tracked by rulesync and distributed with the harness together with its owning `better-*` skills.
- `frontend-verify`: inspect the actual browser state and capture screenshots through a headless browser (`agent-browser`).
- `figma-implement`: use when the request is direct production implementation from Figma rather than exploratory prototyping. This one ships with the harness on Claude Code but is excluded on non-Claude runtimes (it depends on the Figma MCP), so treat it as optional too.

Do not pretend a skill ran. If `baoyu-design` or `figma-implement` is not installed, report the missing dependency and the verification limits it implies, then continue on the available path described in Routes. If `better-interface` or one of its owning `better-*` skills is missing, treat that as an incomplete rulesync/bootstrap state rather than a project-local optional dependency: report the missing skill and continue with the available review path without claiming holistic coverage. If the Impeccable CLI cannot run because its pinned package cannot be fetched or executed, record the preflight as unavailable and continue with `better-interface` / `frontend-verify`; do not claim deterministic coverage.

Before installing `baoyu-design`, read the SKILL.md you are about to install and confirm it is a sane instruction set. Its install command tracks the upstream default branch rather than a pinned revision, so this reading is the point at which a substituted upstream would be caught. `jakubkrehel/skills` is not installed ad hoc here; its source is declared in `rulesync.jsonc` and pinned in `rulesync.lock`.

## 生成プロトタイプの言語（必須）

`baoyu-design` に self-contained prototype や HTML を生成させるときは、生成指示に「ユーザー向け文言は日本語、Standalone HTML は `<html lang="ja">`」を明記する。タイトル、見出し、説明、ボタン、状態表示、図中ラベル、案内まで日本語にする。コード識別子、ファイルパス、API 名などの技術トークンは原文を維持してよいが、周囲の説明は日本語にする。生成物を受け取ったら、英語の UI 文言や `<html lang="en">` が残っていないことを確認してから次の工程へ進む。ユーザーが別の言語を明示した場合だけ、その指定を優先する。

## Routes

### New design or uncertain direction

1. Clarify the user goal, target screen, users, states, constraints, and what is explicitly out of scope.
2. Use `baoyu-design` when available and useful for exploration, with the Japanese language requirement above. Otherwise develop the direction with the available tools.
3. Record the selected direction and design-system decisions before production implementation.
4. Implement in the existing component/token conventions; do not copy prototype code blindly into production.
5. Select verification using the scope table below; record evidence and any unavailable checks.

### Existing Figma design

1. If the goal is a production screen, use `figma-implement` when it is installed (or `baoyu-design` for import/prototyping when that is the explicit goal). With neither installed, say so and implement directly from the design against the repository's own components and tokens.
2. Preserve the repository's existing components, tokens, responsive conventions, and accessibility behavior.
3. Select verification using the scope table below.

### Review-only request

1. Determine whether the user wants source review, visual review, or both.
2. Select only the relevant checks below. Review-only requests do not authorize fixes.
3. Separate verified detector findings, inferred design issues, and observed runtime issues.

## Verification scope

| Scope | Checks |
| --- | --- |
| Copy-only or a small change to an existing component | Check the diff and existing targeted tests. Use browser evidence when wrapping, layout, or interaction may change; no automatic full design audit. |
| New screen, layout, or interaction changes | Use `frontend-verify` for affected states, responsive behavior, and keyboard interaction. Add `impeccable-preflight` for applicable static checks. |
| Holistic design/accessibility review requested | Use `better-interface`; use `impeccable-preflight` for applicable source checks and `frontend-verify` for rendered claims. |
| A specific design concern | Use the owning `better-*` skill rather than the full suite; verify relevant runtime behavior where needed. |

Select by the change and user request, not by a fixed sequence. Reuse evidence already obtained for the same revision and states. Missing tools limit what can be claimed; they do not authorize installation or unrelated work.

## Review handoff

Return a short record of the checks actually selected; omit unused layers. Include:

- selected design direction or source design reference;
- implementation scope and intentionally unsupported states;
- `impeccable-preflight` targets, retained primary findings, relevant advisory findings, and intentional exceptions;
- `better-interface` findings, grouped by severity;
- `frontend-verify` evidence (URL/state/screenshots);
- unresolved decisions and recommended next action.

The layers have different authority. `impeccable-preflight` is deterministic guardrail evidence, not a mandate to redesign around detector preferences. `better-interface` supplies design judgment, but must still respect explicit product and design-system intent. `frontend-verify` supplies rendered evidence, not a substitute for accessibility or design judgment. Conversely, textual review is not proof that the rendered screen is correct.
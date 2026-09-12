---
name: uiux-workflow
description: Orchestrate frontend design work from exploration through implementation and review. Use for UI/UX requests, Figma reconstruction, prototypes, design-system-aware frontend changes, or pre-release visual review.
user-invocable: true
---

# UI/UX workflow

Coordinate the design and review tools without replacing their specialist work.

## Tool roles

- `baoyu-design`: explore directions, create prototypes, import Figma/HTML/GitHub context, and author or preview a design system. This is an optional external skill.
- `better-interface`: review the implemented interface across UI polish, typography, colour, layout, writing, and accessibility. This is an external skill from `jakubkrehel/skills`, tracked by rulesync and distributed with the harness together with its owning `better-*` skills.
- `frontend-verify`: inspect the actual browser state and capture screenshots through a headless browser (`agent-browser`).
- `figma-implement`: use when the request is direct production implementation from Figma rather than exploratory prototyping. This one ships with the harness on Claude Code but is excluded on non-Claude runtimes (it depends on the Figma MCP; see `disabled-skills.json`), so treat it as optional too.

Do not pretend a skill ran. If `baoyu-design` or `figma-implement` is not installed, report the missing dependency and the verification limits it implies, then continue on the available path described in Routes. If `better-interface` or one of its owning `better-*` skills is missing, treat that as an incomplete rulesync/bootstrap state rather than a project-local optional dependency: report the missing skill and continue with the available review path without claiming holistic coverage.

Before installing `baoyu-design`, read the SKILL.md you are about to install and confirm it is a sane instruction set. Its install command tracks the upstream default branch rather than a pinned revision, so this reading is the point at which a substituted upstream would be caught. `jakubkrehel/skills` is not installed ad hoc here; its source is declared in `rulesync.jsonc` and pinned in `rulesync.lock`.

## 生成プロトタイプの言語（必須）

`baoyu-design` に self-contained prototype や HTML を生成させるときは、生成指示に「ユーザー向け文言は日本語、Standalone HTML は `<html lang="ja">`」を明記する。タイトル、見出し、説明、ボタン、状態表示、図中ラベル、案内まで日本語にする。コード識別子、ファイルパス、API 名などの技術トークンは原文を維持してよいが、周囲の説明は日本語にする。生成物を受け取ったら、英語の UI 文言や `<html lang="en">` が残っていないことを確認してから次の工程へ進む。ユーザーが別の言語を明示した場合だけ、その指定を優先する。

## Routes

### New design or uncertain direction

1. Clarify the user goal, target screen, users, states, constraints, and what is explicitly out of scope.
2. Invoke `baoyu-design` to produce one or more self-contained prototypes or a design direction, with the Japanese language requirement above included in the prompt.
3. Record the selected direction and design-system decisions before production implementation.
4. Implement in the existing component/token conventions; do not copy prototype code blindly into production.
5. Invoke `better-interface` for the implementation review.
6. Invoke `frontend-verify` for the final live-browser evidence.

### Existing Figma design

1. If the goal is a production screen, use `figma-implement` when it is installed (or `baoyu-design` for import/prototyping when that is the explicit goal). With neither installed, say so and implement directly from the design against the repository's own components and tokens.
2. Preserve the repository's existing components, tokens, responsive conventions, and accessibility behavior.
3. Run `better-interface`, then `frontend-verify`.

### Review-only request

1. Determine whether the user wants source review, visual review, or both.
2. Run `better-interface` for source/design-quality findings when installed.
3. Run `frontend-verify` for actual browser behavior and screenshots.
4. Separate inferred design issues from verified runtime issues. Do not apply review fixes unless requested.

## Review handoff

Return a short record containing:

- selected design direction or source design reference;
- implementation scope and intentionally unsupported states;
- `better-interface` findings, grouped by severity;
- `frontend-verify` evidence (URL/state/screenshots);
- unresolved decisions and recommended next action.

`frontend-verify` is evidence collection, not a substitute for accessibility or design judgment. Conversely, a textual review is not proof that the rendered screen is correct.
---
name: impeccable-preflight
description: Run Impeccable's deterministic frontend detector before subjective UI review. Use for implemented frontend/UI changes to catch machine-detectable anti-patterns, accessibility, responsive, typography, layout, and design-system issues without treating detector output as design truth.
---

# Impeccable preflight

Run a deterministic UI-quality pass before subjective design review. This skill is a guardrail, not a replacement for `better-interface`, `frontend-verify`, repository design conventions, or product judgment.

## Scope

Use this after frontend code has been implemented or changed and before `better-interface` / `frontend-verify`.

Prefer the narrowest useful target:

- changed UI files when the detector can analyze them directly;
- the affected frontend package/app directory when imports or linked styles matter;
- a URL only when a rendered-page detector pass is explicitly useful. `frontend-verify` remains the primary live-browser evidence path.

Do not scan an entire monorepo by default when the UI change is localized.

## Run

The harness intentionally invokes the deterministic CLI directly instead of installing Impeccable's full opinionated workflow. Use the pinned CLI version so review behavior does not silently drift:

```bash
npx --yes impeccable@4.1.0 detect --json <target...>
```

Examples:

```bash
npx --yes impeccable@4.1.0 detect --json src/components/ProfileCard.tsx
npx --yes impeccable@4.1.0 detect --json apps/web/src/
npx --yes impeccable@4.1.0 detect --json https://localhost:3000/settings
```

Interpret exit status correctly:

- `0`: scan completed with no primary findings; advisory findings may still exist;
- `1`: at least one requested target could not be scanned — this is an operational failure;
- `2`: scan completed and found one or more primary findings — this is expected detector output, not a CLI failure.

If `npx` cannot fetch/run the pinned CLI because of network, runtime, or policy restrictions, report that the deterministic preflight did not run and continue with the available review path. Never claim detector coverage when it did not execute.

## Triage findings

Treat findings as candidate defects, not automatic requirements.

1. Separate primary findings from advisory findings.
2. Verify each material finding against the actual code, repository conventions, design system, and user brief.
3. Fix clear implementation defects when the task includes implementation/fixes.
4. For review-only requests, report findings without changing code.
5. If a rule conflicts with an intentional product/design decision, keep the decision and document the exception rather than redesigning to satisfy the detector.

Impeccable supports project-level detector ignores and inline `impeccable-disable*` comments. Add an ignore only for a stable, intentional exception with a short reason. Do not blanket-disable rules merely to obtain a clean scan.

## Boundaries

- Do not automatically run Impeccable's subjective transformation commands (`bolder`, `delight`, `colorize`, `overdrive`, etc.).
- Do not let an Impeccable preference override an explicit design brief, established brand rule, or repository component/token convention.
- Do not duplicate `better-interface`: detector findings should cover deterministic signals; holistic hierarchy, clarity, visual coherence, writing, and design judgment stay with `better-interface`.
- Do not duplicate `frontend-verify`: rendered state, screenshots, responsive behavior in the running app, and interactions stay with the browser verification step.

## Handoff

Return a compact preflight record containing:

- targets scanned;
- CLI exit status;
- primary findings retained after verification;
- advisory findings worth carrying forward;
- intentional exceptions / ignores;
- whether the scan was incomplete or unavailable.

# fragments — additive instruction composition

Shared blocks used to assemble thin runtime-specific instruction files. Targets opt in with
`<!-- include: <repo-path> -->` and `expandIncludes: true`; distribution expands them deterministically.

- Keep runtime-specific instructions in `packages/targets/<target>/`.
- Put a fragment here only after at least two targets need the same always-loaded text.
- Prefer additive composition over generating one runtime's instructions by subtracting sections from another.
- `agents-md/` contains the minimal resident rules and on-demand routing shared by AGENTS.md targets.
- `claude-md/` holds sections of `core/CLAUDE.md` that depend on personal tooling (rtk, gwm). These are
  split for a different reason than sharing — the public slim distribution
  (`packages/public-slim/manifest.json`) excludes them, so a reader without those tools does not carry
  resident instructions that cannot apply. The Claude target expands them, so what it receives is unchanged.
  The two-target rule above does not apply to this directory.

Do not place full rules, workflow history, or runtime tool syntax here. Those belong in `rules/`, skills,
or the target adapter so the resident prompt stays small.

---
name: upgrade
description: Upgrade all development tools — mise, OpenCode, Homebrew — in one go. Use when the user says "upgrade everything" or "update all packages".
---

# Upgrade Skill

## Process

Run the requested upgrades in order and record each command's exit status. Independent upgrades may continue after a failure; preserve the failure in the report instead of hiding it with `|| true`.

### 1. Upgrade mise

```bash
mise upgrade --bump
```

### 2. Upgrade OpenCode

```bash
opencode upgrade
```

### 3. Upgrade Homebrew

```bash
brew upgrade
```

Run `brew cleanup` only when cleanup is also requested; it removes old package versions.

### 4. Check Pinned Tool Updates (harness-wide)

If running in the harness repository, inspect pinned tools across `mise-global/mise.local.toml` and `mise.toml`:

```bash
python3 scripts/check-tool-updates.py
```

Report any detected updates (e.g. rulesync, jactionlint, pi, omp).

### 5. Summary & Modernization

Report which of mise / OpenCode / Homebrew succeeded or failed, and any detected pinned tool updates. If packages or tools were upgraded, suggest or run `workflow-modernize` to review and optimize custom skills and workflows with new capabilities and eliminate obsolete workarounds.

## Notes

- Record versions before and after the upgrades. Retry a failed step after resolving its cause; do not repeat successful upgrades just to check them.
- To audit and modernize custom skills or workflows after tool upgrades, use `workflow-modernize`.

---
name: upgrade
description: Upgrade all development tools — mise, OpenCode, Homebrew — in one go. Use when the user says "upgrade everything" or "update all packages".
---

# Upgrade Skill

## Process

Run each step in order. Continue to the next step even if one fails (`|| true` for non-critical failures), then report which succeeded and which failed.

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
brew cleanup
```

`brew cleanup` removes old package versions to free disk space.

### 4. Summary

Report which of mise / OpenCode / Homebrew succeeded or failed.

## Notes

- Each step is idempotent — safe to run repeatedly.

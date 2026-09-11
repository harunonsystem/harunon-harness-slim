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

### 4. Summary

Report which of mise / OpenCode / Homebrew succeeded or failed.

## Notes

- Record versions before and after the upgrades. Retry a failed step after resolving its cause; do not repeat successful upgrades just to check them.

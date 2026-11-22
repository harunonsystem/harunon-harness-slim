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

Upgrade formulae first, then casks non-interactively without quitting running apps. Record each command's exit status separately instead of hiding failures with `|| true`:

```bash
brew upgrade --formula --yes
```

```bash
brew upgrade --cask --yes --no-quit
```

If a cask blocks on an interactive `sudo` password prompt (such as launchctl service removal) or emits deprecation or untrusted-tap warnings, stop that cask rather than hanging or bypassing, report the manual `brew upgrade --cask <name>` command, and preserve the warnings in the report.

Run `brew cleanup` only when cleanup is also requested; it removes old package versions.

### 4. Check Pinned Tool Updates (harness-wide)

Resolve the harness repository from the current working directory (`./scripts/check-tool-updates.py`) or, when running outside it, from the parent directory of `~/.config/mise/conf.d/harunon-harness` if it contains `scripts/check-tool-updates.py`. Inspect pinned tools across `mise-global/mise.local.toml` and `mise.toml`:

```bash
python3 "<harness-repo>/scripts/check-tool-updates.py"
```

Report the exit status (0 = up to date, 1 = updates found, 2 = incomplete or failed) and any detected updates (e.g. rulesync, jactionlint, pi, omp).

### 5. Vulnerability Audit

Check installed tools against OSV.dev advisories:

```bash
mise audit
```

Note that `mise audit` exits with code `1` when known vulnerabilities exist. Do not treat exit `1` as a crash or mask it; report any affected tools, advisory IDs, and fixed versions (and suggest `mise upgrade --vulnerable` when a fix is available).

### 6. Summary & Modernization

Report the status and exit code of mise, OpenCode, Homebrew formulae, Homebrew casks, harness pinned tool checks, and `mise audit` results. If packages or tools were upgraded, suggest or run `workflow-modernize` to review and optimize custom skills and workflows with new capabilities and eliminate obsolete workarounds.

## Notes

- Record versions before and after the upgrades. Retry a failed step after resolving its cause; do not repeat successful upgrades just to check them.
- To audit and modernize custom skills or workflows after tool upgrades, use `workflow-modernize`.

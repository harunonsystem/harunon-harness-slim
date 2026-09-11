# ADR-008: hash-bound distribution ledger for deletion propagation

## Status: Accepted (Amended 2026-09-03)

## Context

Removing a managed skill, hook, or plugin from the SSOT did not remove its old live copy. Blanket
`--prune` is not a safe default because runtime config directories also contain user-managed assets.

## Decision

Each successful push atomically records `.harness-distributed.json` with a schema version, target name,
and SHA-256 for every manifest file. A later push may remove an absent manifest file only when:

- the ledger is valid and belongs to the same target;
- its relative path is safe and still resolves inside the target config directory;
- its destination was fully resolved (an unavailable extras source makes that destination incomplete);
- the live bytes still match the hash previously distributed by the harness.

Removed files are backed up. Modified files and symlinks are preserved and remain pending in the ledger.
Corrupt, unsupported, unsafe, or cross-target ledgers fail before live files are overwritten. The ledger is
written through an atomic replace only after the complete push succeeds. Explicit `obsoleteFiles` remains
the migration mechanism for known pre-ledger artifacts; `--prune` remains an explicit broad cleanup tool.

## Consequences

- SSOT deletion propagates without treating every unknown live file as disposable.
- User modifications cannot be silently deleted by ordinary push.
- Missing private submodules cannot make previously distributed private files appear stale.
- The ledger covers resolved manifest files, not settingsSync or runtime-owned local configuration.

## Update 2026-09-03

Manifest entries may now be *derived* rather than declared one-to-one. A `<hooks dir>/lib/`
distribute entry with `hookLibClosure: true` (ADR-003 amendment) contributes only the transitive
closure of `$HOOK_DIR/lib/<name>.sh` references made by the hook files distributed into
`<hooks dir>/`. Each resolved lib is an ordinary manifest file with its own SHA-256 in the ledger, so
the guarantees above are unchanged: when a hook stops referencing a lib, the lib leaves the manifest
and the next push removes the live copy through the hash-bound path (backed up; a user-modified
copy is preserved). The unit of the ledger stays "resolved manifest file"; what changed is that the
resolver, not the target config, decides which lib files belong to the manifest.

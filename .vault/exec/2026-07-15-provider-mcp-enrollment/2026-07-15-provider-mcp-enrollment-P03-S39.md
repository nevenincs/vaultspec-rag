---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S39'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make rollback file replacement collision-safe and metadata-preserving

## Scope

- `src/vaultspec_rag/commands/_install.py and real rollback collision tests`

## Description

- Replace predictable rollback scratch paths with same-directory, random,
  exclusively created temporary files.
- Write snapshot bytes only through the descriptor returned by `mkstemp`, flush
  and fsync the payload, preserve the captured regular-file mode, and publish
  through `os.replace`.
- Clean up only the exact temporary node created by the current restore and
  retain directory permissions during directory restoration.
- Exercise regular-file and symlink restoration against pre-existing regular,
  live-symlink, and broken-symlink collisions at the former predictable name.

## Outcome

The six-case collision matrix and the existing symlink and junction rollback
surface pass 13 focused tests. The complete install, mode, torch, native-host,
and rollback surface passes 208 tests. Ruff, formatting, Ty, BasedPyright,
diff hygiene, and both source and wheel builds pass.

## Notes

The collision assertions prove that neither pre-existing scratch-name nodes nor
their link targets are mutated and that no random rollback temporary is left
behind. S40 restarts the exact 1,820-test release aggregate from zero.

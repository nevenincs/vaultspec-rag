---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:5034e57d15afb127f64a0f22184a3f23781d6b5ad9a67beae761b7eadefefd5b'
step_id: 'S02'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Stamp an archive's own completion timestamp into its snapshot manifest so retention has an age that belongs to the archive

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

- Stamp `completed_at` at snapshot-manifest publication with an aware UTC instant.
- Assert the emitted stamp is UTC and falls inside the real write interval despite an adjacent copied metadata artifact carrying a 31-day-old mtime.
- Mutation-prove the guard by renaming the output key and by backdating the written timestamp; each focused assertion failed for its intended reason, then passed after restoration.

## Outcome

`test_storage_manifest.py` passed 19 tests. Focused format, lint, and type checks passed. The broader storage pair was interrupted by an unrelated shared-WIP `IndentationError` in `job_manager/_persistence.py` while importing the job registry.

## Notes

The timestamp is stamped after snapshot artifacts have been moved and immediately before the atomic manifest write, so it cannot inherit copied metadata's source modification time.

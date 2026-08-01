---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:8ecb21bca51e09f02c447f64c9da6cefafb1d1d7505635b5811577694b7485d2'
step_id: 'S05'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Exercise real Qdrant-output rollover, retention, restart append, and diagnostic continuity

## Scope

- `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`

## Description

- Exercise rollover, sparse retention, zero-backup mode, append after restart, and persistence failure with real files.
- Exercise inherited-pipe timeout and later safe respawn with real subprocesses.
- Assert the diagnostic ring remains bounded and available.

## Outcome

Ten Qdrant supervisor diagnostic tests pass, including the one-writer regression.

## Notes

No mocks, stubs, patches, skips, or xfails were introduced.

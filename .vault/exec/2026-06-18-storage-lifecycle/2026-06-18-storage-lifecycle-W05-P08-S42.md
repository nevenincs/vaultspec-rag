---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S42'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a storage migrate CLI command with dry-run, confirmation, and json

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add the server storage migrate CLI (ROOT --to server|local), dry-run/--yes/--json, with the local-path containment guard.

## Outcome

migrate --help loads; path guard rejects traversal. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

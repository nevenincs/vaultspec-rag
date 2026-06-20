---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
step_id: 'S29'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a storage prune CLI command with a dry-run preview of exact targets, confirmation, and json

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add the server storage prune CLI: dry-run/--yes/--json, exit codes.

## Outcome

Live dry-run reports 0 orphaned / 84 unknown left untouched - the safe default. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

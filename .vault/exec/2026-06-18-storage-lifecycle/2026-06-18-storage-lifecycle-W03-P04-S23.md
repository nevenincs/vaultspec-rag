---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S23'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a storage delete CLI command with a required explicit target, dry-run preview, confirmation, and json

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add the server storage delete CLI: required prefix arg, dry-run/--yes/--json (json-requires-yes), --allow-unknown, exit 3 not-running, exit 1 unconfirmed.

## Outcome

Live dry-run on a missing prefix reports skipped no_such_namespace. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

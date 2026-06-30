---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S07'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Write and update the manifest entry whenever a root is indexed

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Record each server-mode root in the storage manifest from VaultStore.ensure_table / ensure_code_table; idempotent write skips when unchanged; failures logged, never raised.

## Outcome

Manifest populates at index time so survey/prune can attribute namespaces. Real-backend test confirms ensure_table records the root and survey then classifies it live. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S27'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Implement a service-domain prune that selects orphaned namespaces from the manifest and never targets unknown namespaces

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Add prune_orphaned service op: reclaim only orphaned namespaces, skip unknown, dry-run aware, sync-vocabulary results.

## Outcome

Typed PruneResult; covered by the dry-run-then-apply integration test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

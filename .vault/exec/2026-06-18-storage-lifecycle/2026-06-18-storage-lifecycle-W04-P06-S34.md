---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S34'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Guarantee prune and delete never remove unattributable unknown namespaces without an explicit separate gate

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Guarantee prune and delete never remove an unattributable unknown namespace without an explicit gate (delete --allow-unknown).

## Outcome

Proven by the prune-invariant and delete-refuses-unknown tests. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

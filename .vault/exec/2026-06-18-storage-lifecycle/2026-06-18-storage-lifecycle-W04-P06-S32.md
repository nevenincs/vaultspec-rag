---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S32'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Enforce that every destructive op operates only on the resolved root namespaces or managed storage tree and rejects roots outside the allowed base

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Enforce that destructive ops act only on attributable, prefix-scoped namespaces; the prune-invariant test proves out-of-scope namespaces are never touched.

## Outcome

Covered by the prune live+orphaned+unknown invariant test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

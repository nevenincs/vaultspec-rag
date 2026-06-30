---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S33'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Reject path traversal and symlink escape in any path the surface deletes

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Reject path traversal and symlink escape via storage_safety.resolve_within; migrate applies it to its local store path before opening any on-disk store.

## Outcome

Unit tests (traversal, sibling, prefix-lookalike) plus the adversarial traversal test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

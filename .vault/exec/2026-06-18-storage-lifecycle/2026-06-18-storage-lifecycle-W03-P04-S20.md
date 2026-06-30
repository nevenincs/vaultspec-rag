---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S20'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Implement a service-domain delete that releases the in-memory slot before dropping data and returns busy when the root is in use

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Add delete_prefix service op: drop a namespace's collections, refuse an unattributable unknown prefix unless explicitly allowed.

## Outcome

Typed DeleteResult; covered by the unknown-refusal integration test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

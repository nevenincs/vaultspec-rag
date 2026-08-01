---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
body_hash: 'sha256:90e7939d7c9de0f379900c605fb3e594ebaf9dcce4cdfd150f9cef8cec68b7bd'
step_id: 'S25'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Drop the manifest entry on delete

## Scope

- `src/vaultspec_rag/registry.py`

## Description

- Drop the manifest entry on delete via remove_prefix.

## Outcome

Manifest forgets the deleted namespace; covered by integration. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

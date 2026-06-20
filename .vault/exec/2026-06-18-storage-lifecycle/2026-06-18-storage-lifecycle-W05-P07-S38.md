---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
step_id: 'S38'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Research and select the most capable C-backed Python tooling for ultrafast bulk vector and payload movement and record a reference document

## Scope

- `.vault/reference/2026-06-18-storage-lifecycle-migrate-tooling-reference.md`

## Description

- Run the bounded fast-tooling research spike and record a reference: built-in migrate, gRPC + parallel upload_points fast path, snapshots server-only, local-scroll caveats.

## Outcome

Reference doc 2026-06-18-storage-lifecycle-reference captures the decision. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

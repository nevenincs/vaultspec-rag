---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
step_id: 'S19'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add real-backend survey tests for server and local classifying live, orphaned, and unknown

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey.py`

## Description

- Add real-backend survey integration tests against an isolated temp Qdrant (no GPU).

## Outcome

Survey classifies live/orphaned/unknown correctly; green. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

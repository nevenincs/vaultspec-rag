---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
step_id: 'S12'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Compute daemon-side byte footprint for each namespace from the server storage tree

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Add collection_footprints: sum on-disk bytes per collection from the server storage tree (Qdrant exposes no size API).

## Outcome

Footprint surfaced in survey; exercised by the survey integration test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.

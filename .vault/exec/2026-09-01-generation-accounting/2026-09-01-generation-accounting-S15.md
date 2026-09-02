---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:2896920cd02796eb785d170b771429e7f38289fb8f58c90f00bd8fcfa496c9a6'
step_id: 'S15'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Retain the deleted root identity through prefix-addressed server-storage deletion for resident-service eviction

## Scope

- `src/vaultspec_rag/storage_survey_ops.py`

## Description

- Capture the manifest-attributed root before deleting its prefix entry.
- Carry the root in the internal successful deletion result.
- Pass the retained root directly to resident-service eviction.

## Changes

- Extended `DeleteResult` with private teardown root context.
- Removed the post-deletion manifest lookup from `_evict_torn_down_root`.

## Outcome

Prefix-addressed deletion retains the only authoritative root identity long enough to evict
the resident project without changing the operator-facing result schema.

## Notes

The associated prefix-form regression is tracked separately as S16.

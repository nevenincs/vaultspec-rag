---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:75979cc73e7e8dda7889a8a3c57496a79a914e50544fbbef8ee685d4e7136af4'
step_id: 'S16'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove prefix-addressed deletion retains the attributed root required for resident-service eviction

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_delete_addressing.py`

## Description

- Register a real root and create its managed Qdrant namespace.
- Delete by prefix through `delete_prefix`.
- Assert manifest removal and retained root identity in the same successful result.

## Changes

- Added the prefix-deletion root-retention regression at the real storage/manifest boundary.

## Outcome

The resident-service eviction caller receives the exact registered root even though the
manifest no longer contains the deleted prefix.

## Notes

The integration selection uses the repository's pinned Qdrant service guard and is not
bypassed when that compatible service is unavailable.

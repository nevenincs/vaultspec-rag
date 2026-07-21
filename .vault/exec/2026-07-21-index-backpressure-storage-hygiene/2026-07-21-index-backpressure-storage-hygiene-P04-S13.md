---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S13'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# stamp ephemeral (root under the platform temp dir) and refresh a persisted last_indexed timestamp at manifest registration

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

The manifest already carried a `last_indexed` field that nothing stamped.
Added `VaultStore.touch_manifest_last_indexed()` (server-mode only,
best-effort, UTC ISO stamp via `record_root`) and wired it at all four
index-run completion sites: codebase full/incremental and vault
full/incremental wrappers (scoped runs flow through the incremental
wrapper). The stamp is the persisted activity clock for the ephemeral
tier; the live re-registration clearing `first_seen_orphaned` on write is
correct (a stamping root is live by definition).

## Outcome

Committed as `feat(storage): persisted last_indexed activity clock stamped by every index run (#242)`; `TestLastIndexedStamping` green.

## Notes

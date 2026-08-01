---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:760427a10bb0848b194df80d2c847bb058854b274127bedfa74ccc44f4d743e7'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# `index-backpressure-storage-hygiene` `P05` summary

## Description

Cheap collections and debris visibility. Empirical measurement on the
pinned qdrant settled the preallocation dispute (empty namespace pair:
~1217 MiB default, ~336 MiB with the adopted wal-16MiB/2-segment config);
survey now surfaces config-less crash debris with footprints; whole-
backend totals flow through the survey envelope and new store gauges;
`prune --debris` gives operators a gated, idempotent removal path.

- Modified: `src/vaultspec_rag/store.py`, `src/vaultspec_rag/storage_ops.py`,
  `src/vaultspec_rag/server/_routes_storage.py`,
  `src/vaultspec_rag/server/_lifecycle.py`,
  `src/vaultspec_rag/cli/_service_storage.py`,
  `src/vaultspec_rag/tests/test_storage_ops.py`

Verification: storage-ops suite green (37); measurement recorded in the
S16 record.

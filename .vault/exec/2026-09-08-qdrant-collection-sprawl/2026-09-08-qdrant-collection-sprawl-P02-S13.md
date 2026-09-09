---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:a4bfbebfe43a13829badf8ab682e66966e48226c0be1cfa506df3df9632566c3'
step_id: 'S13'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a test proving an orphaned temp-rooted point-bearing namespace draws the ephemeral window, not the data window

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

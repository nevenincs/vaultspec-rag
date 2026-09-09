---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:d043d90f6551dcd4aa35376e88b51f8a9eae3f137b904f9cdc2e843b74d69371'
step_id: 'S48'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a retried partial drop leaves both attempts' artifacts restorable

## Scope

- `src/vaultspec_rag/tests/test_storage_restore.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_restore.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_adversarial.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py` -> `pass`

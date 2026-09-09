---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:6f8964247862af3c425fa7956dd1cd9c73abf5f9c0a6e7d8ce1ff86b856d2df9'
step_id: 'S46'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Merge the archive of a retried partial drop into the snapshot manifest already on disk instead of overwriting it, so the first attempt's artifacts stay named

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_adr_regression.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

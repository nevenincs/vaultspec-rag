---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:dbd10d4cb46994e6738919385431d776bece7f486dd8189eb069c32be8b0cd1c'
step_id: 'S36'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a transport timeout during the drop is recorded against that namespace and the cycle continues

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops_reclaim.py test_storage_ops.py test_storage_safety.py` -> `pass`

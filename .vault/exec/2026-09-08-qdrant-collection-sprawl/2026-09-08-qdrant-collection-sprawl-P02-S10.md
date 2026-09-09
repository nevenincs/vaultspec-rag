---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:c4fd1d2d83082e1a45d1bd842bbfde8cb4d234367ecafccdac322a946e8e938a'
step_id: 'S10'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add the ephemeral-orphan window field to the reclaim policy with its documented default

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

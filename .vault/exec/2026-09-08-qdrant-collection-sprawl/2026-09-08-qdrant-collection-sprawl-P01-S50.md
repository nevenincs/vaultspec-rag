---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:bfd4c0ba0c89801d003827d1e2ce2d32a0a5485b64062c87e2fe62a4e918cb67'
step_id: 'S50'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Carry the removed collection names onto the recorded outcome of a partial drop, not only their count

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

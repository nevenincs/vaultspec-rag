---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:60baf35329efd9c97187421b72549cb27e20a0cfcbb886c9979f50754bd5f5e0'
step_id: 'S16'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving the ephemeral window does not bypass the pre-drop point re-count

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_safety.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:240c26636ad7952225432b13b338133aa7a2d65dc6efa9570a2b1e6d7efbc03c'
step_id: 'S15'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving the ephemeral window does not bypass the archive-before-destroy gate

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_safety.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

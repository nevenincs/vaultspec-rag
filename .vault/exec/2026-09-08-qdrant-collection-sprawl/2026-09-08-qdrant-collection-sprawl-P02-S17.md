---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:e5ebeaf299eee28c46b79cd51ab3f5920b2d7bd54e20e124ae3fbe589f0d2dd0'
step_id: 'S17'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving an unknown or unverifiable namespace is still never reached by the ephemeral path

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_safety.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

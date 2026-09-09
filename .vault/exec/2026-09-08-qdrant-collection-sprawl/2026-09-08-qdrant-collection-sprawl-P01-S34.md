---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:c9b36cd6e492a439f57f0da5e75c38d4ff811ff814b00fad82a9fd6eab4223b9'
step_id: 'S34'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Guard the drop call in the apply path so a failing drop becomes a failed decision instead of escaping the cycle

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops.py test_storage_ops_reclaim.py test_storage_safety.py` -> `pass`

---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:49b2001862c7fb69801d692952fa5c773142f5dba4c86d49f05fbd29b1849803'
step_id: 'S29'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Guard the collection enumeration in the pre-drop re-count so a transport timeout yields an unverifiable count instead of escaping

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops.py test_storage_safety.py test_storage_ops_reclaim.py` -> `pass`

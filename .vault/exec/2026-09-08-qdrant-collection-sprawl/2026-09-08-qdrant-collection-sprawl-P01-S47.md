---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:74e2a87c6fcc5c5ef96ffe9b5e7ff95ca72ddc42e64d38e9735cbd8f2192cf2e'
step_id: 'S47'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Refuse to restore an archive directory holding snapshot artifacts its manifest does not name, rather than reporting a partial recovery as complete

## Scope

- `src/vaultspec_rag/storage_restore.py`

## Changes

- `M` `src/vaultspec_rag/storage_restore.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_adversarial.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py` -> `pass`

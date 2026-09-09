---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:9e37f3e8334b4bfa9f663fc37861f40529d351042a527d3f735b219a9c1f28a3'
step_id: 'S12'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Thread the configured ephemeral window into the policy the maintenance tick constructs

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Changes

- `M` `src/vaultspec_rag/server/_lifecycle.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`

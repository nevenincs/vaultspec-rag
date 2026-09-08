---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:3e1cd07142880ec9355073eacd3bf12d6425fc605e2a985d6939da66f89f44bc'
step_id: 'S07'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a snapshot read timeout marks that namespace failed and the cycle continues to the next candidate

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops_reclaim.py::TestTransportTimeoutIsolation::test_a_snapshot_timeout_fails_one_namespace_and_the_cycle_goes_on` -> `pass`

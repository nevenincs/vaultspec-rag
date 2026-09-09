---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cb6a9fad0ba69a02e7d4f7ea43502c1596b607dd7fd948d2d81d0bf6f79d8e61'
step_id: 'S08'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a re-count read timeout defers the namespace rather than aborting the cycle

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops_reclaim.py::TestTransportTimeoutIsolation::test_a_recount_timeout_defers_one_namespace_and_the_cycle_goes_on` -> `pass`

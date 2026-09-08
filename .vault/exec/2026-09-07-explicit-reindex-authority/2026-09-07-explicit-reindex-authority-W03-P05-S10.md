---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:975b38332abd0cdfdae05096251ca766b9e9444be629a0854a0614628ffc68e5'
step_id: 'S10'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Record durable progress for committed reconciliation batches

## Scope

- `src/vaultspec_rag/indexer/_route_migration.py`
- `src/vaultspec_rag/indexer/_run_policy.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_route_migration.py`
- `M` `src/vaultspec_rag/indexer/_run_policy.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_run_policy.py -q -p no:xdist` -> `pass`

---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:54658b7b31361b30e0cff13310debf7ebaed2c0694712c167f807c3237c4bf65'
step_id: 'S02'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Expose requested and effective indexing cost class in job state

## Scope

- `src/vaultspec_rag/job_models.py`

## Changes

- `M` `src/vaultspec_rag/job_models.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_job_contracts.py src/vaultspec_rag/tests/test_job_contracts_persistence.py -q -p no:xdist` -> `pass`

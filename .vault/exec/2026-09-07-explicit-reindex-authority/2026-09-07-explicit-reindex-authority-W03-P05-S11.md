---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:35fb978d4ac491f55668aec70f6376c96b1cd8e3955986d6fcf32c6c8fca53b8'
step_id: 'S11'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Propagate degraded job counts and effective operation through health

## Scope

- `src/vaultspec_rag/server`

## Changes

- `M` `src/vaultspec_rag/server/_lifespan.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_job_manager_degradation.py src/vaultspec_rag/tests/test_health_degraded_clears.py -q -p no:xdist` -> `pass`

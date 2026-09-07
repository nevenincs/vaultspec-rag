---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:876b08e1daf7868ae960937beb2272dc2a781cd7be53fd110609d5569fc9c129'
step_id: 'S14'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Add integration coverage for backend transitions and contended finalization

## Scope

- `src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py`
- `src/vaultspec_rag/tests/test_watcher_retry.py`

## Changes

- `A` `src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py`
- `M` `src/vaultspec_rag/tests/test_watcher_retry.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py src/vaultspec_rag/tests/test_watcher_retry.py -q -p no:xdist --tb=short` -> `pass`

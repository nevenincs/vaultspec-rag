---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:cfa289d81700a18cba9db305830158750285ea79149b3c3a3d4e7cc5ca6795d6'
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
- `M` `.vault/research/2026-09-07-explicit-reindex-authority-research.md`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py src/vaultspec_rag/tests/test_watcher_retry.py -q -p no:xdist --tb=short` -> `pass`

---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:8a19495d39130bc065c1fc0577624ba230bd250c12f793eb53e8918ff06b7d62'
step_id: 'S06'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Carry backend identity through store and checkpoint construction

## Scope

- `src/vaultspec_rag/store_runtime.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `M` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_run_checkpoint.py::test_checkpoint_resumes_only_unconfirmed_segments src/vaultspec_rag/tests/test_document_checkpoint.py::test_generation_id_matches_the_open_generation src/vaultspec_rag/tests/test_index_run_ledger.py::test_generation_transactions_resume_and_invalidate_drift -q -p no:xdist` -> `pass`

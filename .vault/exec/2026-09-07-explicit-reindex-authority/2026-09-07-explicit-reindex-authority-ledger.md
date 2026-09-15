---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:89c548fa7311dfa97405101462b48aa5346d6cccc29c1672c331190a58497f3d'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# `explicit-reindex-authority` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/_job_errors.py`
- `S01` `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_jobs_lifecycle.py -q -p no:xdist` -> `pass`
- `S02` `M` `src/vaultspec_rag/job_models.py`
- `S02` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_job_contracts.py src/vaultspec_rag/tests/test_job_contracts_persistence.py -q -p no:xdist` -> `pass`
- `S03` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S03` `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/indexer/_codebase_indexer.py` -> `pass`
- `S04` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S04` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S04` `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/indexer/_document_indexer.py src/vaultspec_rag/indexer/_vault_indexer.py` -> `pass`
- `S05` `M` `src/vaultspec_rag/store_runtime.py`
- `S05` `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/store_runtime.py` -> `pass`
- `S06` `M` `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `S06` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S06` `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `S06` `M` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `S06` `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `S06` `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `S06` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_run_checkpoint.py::test_checkpoint_resumes_only_unconfirmed_segments src/vaultspec_rag/tests/test_document_checkpoint.py::test_generation_id_matches_the_open_generation src/vaultspec_rag/tests/test_index_run_ledger.py::test_generation_transactions_resume_and_invalidate_drift -q -p no:xdist` -> `pass`
- `S07` `M` `src/vaultspec_rag/_integrity_remediation.py`
- `S07` `M` `src/vaultspec_rag/config/_settings.py`
- `S07` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_integrity_remediation.py::TestOperatorSwitch::test_disabling_auto_repair_keeps_detection_but_never_requests -q -p no:xdist` -> `pass`
- `S08` `M` `src/vaultspec_rag/watcher_retry.py`
- `S08` `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/watcher_retry.py` -> `pass`
- `S09` `M` `src/vaultspec_rag/watcher_retry.py`
- `S09` `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/watcher_retry.py` -> `pass`
- `S10` `M` `src/vaultspec_rag/indexer/_route_migration.py`
- `S10` `M` `src/vaultspec_rag/indexer/_run_policy.py`
- `S10` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_run_policy.py -q -p no:xdist` -> `pass`
- `S11` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S11` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_job_manager_degradation.py src/vaultspec_rag/tests/test_health_degraded_clears.py -q -p no:xdist` -> `pass`
- `S12` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S12` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S12` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S12` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_cli_server_start.py -q -p no:xdist` -> `pass`
- `S13` `M` `src/vaultspec_rag/tests/test_document_index_escalation.py`
- `S13` `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `S13` `M` `src/vaultspec_rag/tests/test_integrity_remediation.py`
- `S13` `M` `src/vaultspec_rag/tests/test_watcher_retry.py`
- `S13` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_integrity_remediation.py src/vaultspec_rag/tests/test_watcher_retry.py::test_full_reindex_required_is_terminal_and_clears_pending_intent src/vaultspec_rag/tests/test_index_run_ledger.py::test_backend_identity_is_part_of_manifest_compatibility -q -p no:xdist` -> `pass`
- `S14` `A` `src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py`
- `S14` `M` `src/vaultspec_rag/tests/test_watcher_retry.py`
- `S14` `M` `.vault/research/2026-09-07-explicit-reindex-authority-research.md`
- `S14` `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py src/vaultspec_rag/tests/test_watcher_retry.py -q -p no:xdist --tb=short` -> `pass`

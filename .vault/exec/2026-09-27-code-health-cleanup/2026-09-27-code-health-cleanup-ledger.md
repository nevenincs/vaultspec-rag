---
tags:
  - '#exec'
  - '#code-health-cleanup'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:08332a7e3a918dc0ee3f4d6f7704f0e00d235c041d0c1d2c239ee5ef66d0ae8c'
related:
  - "[[2026-09-27-code-health-cleanup-plan]]"
---


# `code-health-cleanup` ledger

## Changes


- `S01` `M` `src/vaultspec_rag/_public_search.py`
- `S01` `M` `src/vaultspec_rag/cli/_process.py`
- `S01` `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `S01` `M` `src/vaultspec_rag/indexer/_content_discovery.py`
- `S01` `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `S01` `D` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `S01` `M` `src/vaultspec_rag/search/_typesafe_policy.py`
- `S01` `M` `src/vaultspec_rag/search/_typesafe_transport.py`
- `S01` `M` `src/vaultspec_rag/storage_restore.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/_service_jobs_support.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_codebase_integration_search.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_service_job_control.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `S01` `M` `src/vaultspec_rag/tests/test_checkpoint_common.py`
- `S01` `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `S01` `M` `src/vaultspec_rag/tests/test_encode_bucket_planner.py`
- `S01` `D` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `S01` `M` `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`
- `S01` `M` `src/vaultspec_rag/tests/test_job_manager_quiesce.py`
- `S01` `M` `src/vaultspec_rag/tests/test_jobs_degradation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`
- `S01` `M` `src/vaultspec_rag/tests/test_publication_read_paths.py`
- `S01` `M` `src/vaultspec_rag/tests/test_publication_scaling.py`
- `S01` `M` `src/vaultspec_rag/tests/test_service_quiesce_adapters.py`
- `S01` `M` `src/vaultspec_rag/tests/test_service_quiesce_cli.py`
- `S01` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S01` `M` `src/vaultspec_rag/tests/test_vault_checkpoint.py`
- `S01` `M` `src/vaultspec_rag/tests/test_watcher_recovery.py`
- `S01` `M` `src/vaultspec_rag/tests/test_watcher_transition_logging.py`
- `S01` `M` `src/vaultspec_rag/watcher_intake.py`
- `S01` `M` `src/vaultspec_rag/watcher_runtime.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_publication_identity.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_publication_proofs.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_publication_reads.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_publication_receipts.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_publication_storage.py`
- `S01` `A` `src/vaultspec_rag/tests/_run_ledger_test_support.py`
- `S01` `A` `src/vaultspec_rag/tests/_watcher_job_snapshot.py`
- `S01` `A` `src/vaultspec_rag/tests/integration/test_server_index_concurrency.py`
- `S01` `A` `src/vaultspec_rag/tests/test_cli_auto_delegation.py`
- `S01` `A` `src/vaultspec_rag/tests/test_cli_clean.py`
- `S01` `A` `src/vaultspec_rag/tests/test_cli_index_disk_preflight.py`
- `S01` `A` `src/vaultspec_rag/tests/test_cli_index_summary.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_commit_units.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_compaction.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_generations.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_publication_finalization.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_publication_models.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_publication_reads.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_publication_receipts.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_recovery.py`
- `S01` `A` `src/vaultspec_rag/tests/test_index_run_ledger_schema.py`
- `S01` `verify:` `ledger covering pytest 134 cases` -> `pass`
- `S01` `verify:` `ledger normalized identities 74 before and after` -> `pass`
- `S01` `verify:` `CLI covering pytest 44 cases` -> `pass`
- `S01` `verify:` `stress normalized identities 15 before and after` -> `pass`
- `S01` `verify:` `clone-removal CPU pytest 124 cases` -> `pass`
- `S01` `verify:` `typesafe storage content pytest 174 cases` -> `pass`
- `S01` `verify:` `GPU integration and performance pytest 55 cases` -> `pass`
- `S01` `verify:` `subprocess GPU diagnostics pytest 3 cases` -> `pass`
- `S01` `verify:` `just check-python` -> `pass`
- `S01` `verify:` `just check-type` -> `pass`
- `S01` `verify:` `just check-type-strict` -> `pass`
- `S01` `verify:` `just check-complexity` -> `pass`
- `S01` `verify:` `just check-nesting` -> `pass`
- `S01` `verify:` `just audit-duplication` -> `pass`
- `S01` `verify:` `just audit-complexity` -> `pass`
- `S01` `by:` `vaultspec-team`

## Notes

- `S01` Former S02-S04 combined into S01 for an atomic verified implementation: import migrations, newly split clone owners and shared guard registry must land together. No work or authorized scope was dropped.

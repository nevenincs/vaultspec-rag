---
tags:
  - '#exec'
  - '#destructive-rebuild-lifecycle'
date: '2026-10-12'
modified: '2026-11-21'
body_schema: 'body-v2'
body_hash: 'sha256:e14127b3be9e3b15d66e85d41d12bca0102bfa16437244339f1cb16dd874960b'
related:
  - "[[2026-10-12-destructive-rebuild-lifecycle-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `destructive-rebuild-lifecycle` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->

- `S01` `A` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_source_resets.py`
- `S01` `A` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S01` `M` `src/vaultspec_rag/api.py`
- `S01` `M` `src/vaultspec_rag/_publication_state.py`
- `S01` `M` `src/vaultspec_rag/_store_models.py`
- `S01` `M` `src/vaultspec_rag/store_collections.py`
- `S01` `M` `src/vaultspec_rag/store_ingest.py`
- `S01` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_drift_owner.py`
- `S01` `M` `src/vaultspec_rag/indexer/_incremental_commit.py`
- `S01` `M` `src/vaultspec_rag/indexer/_route_migration.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_proofs.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `S01` `M` `src/vaultspec_rag/tests/test_api_clean_admission.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_document_store.py`
- `S01` `M` `src/vaultspec_rag/tests/test_code_rebuild_stale_evidence.py`
- `S01` `M` `src/vaultspec_rag/tests/test_content_route_migration.py`
- `S01` `M` `src/vaultspec_rag/tests/test_incremental_route_reconciliation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_served_pointer_validation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_store_codebase.py`
- `S01` `M` `src/vaultspec_rag/tests/test_index_run_ledger_schema.py`
- `S01` `M` `src/vaultspec_rag/tests/test_vault_progress_phases.py`
- `S01` `verify:` `ruff check (changed files)` -> `pass`
- `S01` `verify:` `ruff format --check (changed files)` -> `pass`
- `S01` `verify:` `ty check (changed files)` -> `pass`
- `S01` `verify:` `basedpyright (changed files)` -> `pass`
- `S01` `verify:` `pytest run-ledger/store/clean CPU modules -n 8 (1929 passed; 2 failures outside S01 files)` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S02` `M` `src/vaultspec_rag/_store_models.py`
- `S02` `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `S02` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S02` `M` `src/vaultspec_rag/indexer/_consumer_pipeline.py`
- `S02` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S02` `M` `src/vaultspec_rag/indexer/_drift_owner.py`
- `S02` `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `S02` `M` `src/vaultspec_rag/indexer/_incremental_commit.py`
- `S02` `M` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S02` `M` `src/vaultspec_rag/indexer/_route_migration.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_reads.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_receipts.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_recovery.py`
- `S02` `M` `src/vaultspec_rag/indexer/_streaming.py`
- `S02` `M` `src/vaultspec_rag/indexer/_streaming_types.py`
- `S02` `M` `src/vaultspec_rag/indexer/_vault_checkpoint.py`
- `S02` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S02` `M` `src/vaultspec_rag/store_catalog.py`
- `S02` `M` `src/vaultspec_rag/store_collections.py`
- `S02` `M` `src/vaultspec_rag/tests/_ledger_fixtures.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/_index_job_control_support.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_codebase_integration.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_document_search.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_document_store.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_index_job_control_publication.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_indexer_integration.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_store_integration.py`
- `S02` `M` `src/vaultspec_rag/tests/test_code_consumer_progress.py`
- `S02` `M` `src/vaultspec_rag/tests/test_code_pipeline_retained_ids.py`
- `S02` `M` `src/vaultspec_rag/tests/test_code_rebuild_stale_evidence.py`
- `S02` `M` `src/vaultspec_rag/tests/test_content_kind_checkpoint_restart.py`
- `S02` `M` `src/vaultspec_rag/tests/test_content_route_migration.py`
- `S02` `M` `src/vaultspec_rag/tests/test_incremental_receipt_recovery.py`
- `S02` `M` `src/vaultspec_rag/tests/test_incremental_route_reconciliation.py`
- `S02` `M` `src/vaultspec_rag/tests/test_ledger_set_aside.py`
- `S02` `M` `src/vaultspec_rag/tests/test_live_checkpoint_resilience.py`
- `S02` `M` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S02` `M` `src/vaultspec_rag/tests/test_receipt_finalization_recovery.py`
- `S02` `M` `src/vaultspec_rag/tests/test_route_scan_classification_cache.py`
- `S02` `M` `src/vaultspec_rag/tests/test_search_readiness.py`
- `S02` `M` `src/vaultspec_rag/tests/test_served_pointer_validation.py`
- `S02` `M` `src/vaultspec_rag/tests/test_service_registry.py`
- `S02` `M` `src/vaultspec_rag/tests/test_storage_identity.py`
- `S02` `M` `src/vaultspec_rag/tests/test_store.py`
- `S02` `M` `src/vaultspec_rag/tests/test_vault_readiness_publication.py`
- `S02` `M` `src/vaultspec_rag/tests/test_weighted_code_resume.py`
- `S02` `A` `src/vaultspec_rag/tests/integration/test_rebuild_replacement_corpus.py`
- `S02` `A` `src/vaultspec_rag/tests/test_rebuild_replacement.py`
- `S02` `verify:` `ruff check (changed files)` -> `pass`
- `S02` `verify:` `ruff format --check (changed files)` -> `pass`
- `S02` `verify:` `ty check (changed files)` -> `pass`
- `S02` `verify:` `basedpyright (changed files)` -> `pass`
- `S02` `verify:` `pytest -m unit src/vaultspec_rag/tests (8321 passed; failures only in another worker's in-flight test_cli_service_status files and one parallel-lane flake that passes alone)` -> `pass`
- `S02` `verify:` `pytest test_rebuild_lifecycle test_substitution_discipline test_process_probe_source_structure test_rebuild_replacement test_no_unconsumed_definitions` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S03` `M` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S03` `M` `src/vaultspec_rag/_publication_state.py`
- `S03` `M` `src/vaultspec_rag/api.py`
- `S03` `M` `src/vaultspec_rag/_public_search.py`
- `S03` `M` `src/vaultspec_rag/_search_state.py`
- `S03` `M` `src/vaultspec_rag/server/_search_availability.py`
- `S03` `M` `src/vaultspec_rag/server/_search_route_availability.py`
- `S03` `M` `src/vaultspec_rag/server/_routes_search.py`
- `S03` `A` `src/vaultspec_rag/tests/test_search_reset_fence.py`
- `S03` `A` `src/vaultspec_rag/tests/integration/test_service_search_reset_transition.py`
- `S03` `A` `src/vaultspec_rag/tests/integration/test_rebuild_partial_search.py`
- `S03` `M` `src/vaultspec_rag/tests/test_search_conformance_refusal.py`
- `S03` `M` `src/vaultspec_rag/tests/test_typesafe_search.py`
- `S03` `verify:` `ruff check (changed files)` -> `pass`
- `S03` `verify:` `ruff format --check (changed files)` -> `pass`
- `S03` `verify:` `ty check (changed files)` -> `pass`
- `S03` `verify:` `basedpyright (changed files)` -> `pass`
- `S03` `verify:` `pytest rebuild/search-readiness/service/guard modules incl. CPU search-readiness integration (330 passed)` -> `pass`
- `S03` `verify:` `pytest CPU unit lane (8339 passed; 25 failures only in another worker's in-flight test_cli_service_status files)` -> `pass`
- `S03` `by:` `vaultspec-high-executor`
- `S04` `M` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S04` `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `S04` `M` `src/vaultspec_rag/indexer/_run_policy.py`
- `S04` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S04` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S04` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S04` `M` `src/vaultspec_rag/_store_writes.py`
- `S04` `M` `src/vaultspec_rag/job_dispatch.py`
- `S04` `M` `src/vaultspec_rag/job_models.py`
- `S04` `M` `src/vaultspec_rag/job_persistence.py`
- `S04` `M` `src/vaultspec_rag/job_manager/_control.py`
- `S04` `M` `src/vaultspec_rag/job_manager/_progress.py`
- `S04` `M` `src/vaultspec_rag/job_manager/models.py`
- `S04` `M` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S04` `M` `src/vaultspec_rag/tests/test_job_rebuild_resume_dispatch.py`
- `S04` `M` `src/vaultspec_rag/tests/_ledger_fixtures.py`
- `S04` `M` `src/vaultspec_rag/tests/test_content_kind_checkpoint_restart.py`
- `S04` `M` `src/vaultspec_rag/tests/test_weighted_code_resume.py`
- `S04` `M` `src/vaultspec_rag/tests/test_store_writes.py`
- `S04` `M` `src/vaultspec_rag/tests/test_store_codebase.py`
- `S04` `M` `src/vaultspec_rag/tests/test_vault_payload_batching.py`
- `S04` `M` `src/vaultspec_rag/tests/test_code_pipeline_retained_ids.py`
- `S04` `M` `src/vaultspec_rag/tests/test_content_route_migration.py`
- `S04` `M` `src/vaultspec_rag/tests/test_receipt_finalization_recovery.py`
- `S04` `M` `src/vaultspec_rag/tests/test_job_contracts_persistence.py`
- `S04` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S04` `verify:` `ruff format --check (changed files)` -> `pass`
- `S04` `verify:` `ty check (changed files)` -> `pass`
- `S04` `verify:` `basedpyright (changed files)` -> `pass`
- `S04` `verify:` `pytest -n 8 CPU lane src/vaultspec_rag/tests (8379 passed)` -> `pass`
- `S04` `verify:` `pytest test_rebuild_lifecycle.py test_job_rebuild_resume_dispatch.py` -> `pass`
- `S04` `verify:` `mutation proofs, 8 guards break-fail-restore-pass` -> `pass`
- `S04` `by:` `vaultspec-high-executor`
- `S05` `M` `src/vaultspec_rag/_store_models.py`
- `S05` `M` `src/vaultspec_rag/_store_search.py`
- `S05` `M` `src/vaultspec_rag/cli/_service_storage.py`
- `S05` `D` `src/vaultspec_rag/generation_stamps.py`
- `S05` `D` `src/vaultspec_rag/generation_survey.py`
- `S05` `M` `src/vaultspec_rag/indexer/_donor_candidates.py`
- `S05` `M` `src/vaultspec_rag/server/_routes_storage.py`
- `S05` `M` `src/vaultspec_rag/service.py`
- `S05` `M` `src/vaultspec_rag/storage_migration.py`
- `S05` `M` `src/vaultspec_rag/storage_reclamation.py`
- `S05` `M` `src/vaultspec_rag/storage_survey.py`
- `S05` `M` `src/vaultspec_rag/store_catalog.py`
- `S05` `M` `src/vaultspec_rag/store_collections.py`
- `S05` `M` `src/vaultspec_rag/store_ingest.py`
- `S05` `M` `src/vaultspec_rag/store_runtime.py`
- `S05` `A` `src/vaultspec_rag/tests/_historical_code_layout.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_first_build_lifecycle.py`
- `S05` `D` `src/vaultspec_rag/tests/integration/test_generation_reclaim.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_index_job_control_managed.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_index_job_control_publication.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_index_job_control_stream.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_rebuild_replacement_corpus.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- `S05` `M` `src/vaultspec_rag/tests/integration/test_store_integration.py`
- `S05` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S05` `M` `src/vaultspec_rag/tests/test_cli_storage_generation_diagnostics.py`
- `S05` `M` `src/vaultspec_rag/tests/test_content_route_migration.py`
- `S05` `M` `src/vaultspec_rag/tests/test_donor_admission.py`
- `S05` `M` `src/vaultspec_rag/tests/test_first_build_admission.py`
- `S05` `M` `src/vaultspec_rag/tests/test_generation_autoprune_policy.py`
- `S05` `D` `src/vaultspec_rag/tests/test_generation_survey.py`
- `S05` `M` `src/vaultspec_rag/tests/test_incremental_failure_classification.py`
- `S05` `M` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S05` `M` `src/vaultspec_rag/tests/test_rebuild_replacement.py`
- `S05` `M` `src/vaultspec_rag/tests/test_served_pointer_validation.py`
- `S05` `M` `src/vaultspec_rag/tests/test_storage_identity.py`
- `S05` `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `S05` `M` `src/vaultspec_rag/tests/test_store_codebase.py`
- `S05` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S05` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S05` `verify:` `ruff format --check (changed files)` -> `pass`
- `S05` `verify:` `ty check (changed files)` -> `pass`
- `S05` `verify:` `basedpyright (changed files)` -> `pass`
- `S05` `verify:` `python -m dev lint size` -> `pass`
- `S05` `verify:` `python -m dev lint complexity` -> `pass`
- `S05` `verify:` `pytest -m unit -n 8 src/vaultspec_rag/tests (8346 passed; 1 stale guard fixed, module rerun 25 passed)` -> `pass`
- `S05` `verify:` `pytest store/generation/survey/reclamation/status/rebuild modules plus rebuild_lifecycle, rebuild_replacement, search_reset_fence, substitution_discipline, no_unconsumed_definitions, no_reexports, process_probe_source_structure` -> `pass`
- `S05` `verify:` `mutation proofs, 9 guards break-fail-restore-pass` -> `pass`
- `S05` `by:` `vaultspec-high-executor`
- `S06` `M` `README.md`
- `S06` `M` `docs/automatic-convergence.md`
- `S06` `M` `docs/glossary.md`
- `S06` `M` `docs/indexing.md`
- `S06` `M` `docs/search-and-index.md`
- `S06` `M` `docs/service-mode.md`
- `S06` `M` `docs/storage-maintenance.md`
- `S06` `M` `src/vaultspec_rag/_index_integrity.py`
- `S06` `M` `src/vaultspec_rag/_job_errors.py`
- `S06` `M` `src/vaultspec_rag/_publication_state.py`
- `S06` `M` `src/vaultspec_rag/_source_types.py`
- `S06` `M` `src/vaultspec_rag/_store_models.py`
- `S06` `M` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S06` `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `S06` `M` `src/vaultspec_rag/server/_health.py`
- `S06` `M` `src/vaultspec_rag/server/_routes_reindex.py`
- `S06` `M` `src/vaultspec_rag/server/_search_readiness.py`
- `S06` `M` `src/vaultspec_rag/service.py`
- `S06` `M` `src/vaultspec_rag/store_collections.py`
- `S06` `M` `src/vaultspec_rag/watcher_retry_policy.py`
- `S06` `A` `src/vaultspec_rag/tests/integration/test_rebuild_three_domain_contract.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/test_rebuild_replacement_corpus.py`
- `S06` `M` `src/vaultspec_rag/tests/test_health_degraded_clears.py`
- `S06` `M` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S06` `M` `src/vaultspec_rag/tests/test_rebuild_replacement.py`
- `S06` `M` `src/vaultspec_rag/tests/test_search_reset_fence.py`
- `S06` `M` `src/vaultspec_rag/tests/test_served_pointer_validation.py`
- `S06` `M` `src/vaultspec_rag/tests/test_watcher_retry.py`
- `S06` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S06` `verify:` `ruff format --check (changed files)` -> `pass`
- `S06` `verify:` `ty check (changed files)` -> `pass`
- `S06` `verify:` `basedpyright (changed files)` -> `pass`
- `S06` `verify:` `python -m dev lint size` -> `pass`
- `S06` `verify:` `python -m dev lint complexity` -> `pass`
- `S06` `verify:` `python -m dev.generate_cli_reference --check` -> `pass`
- `S06` `verify:` `pytest -m unit -n 8 (8253 passed; 101 parallel-load failures rerun serially: 96 pass, 5 test_service_runtime failures from another worker's in-flight torch_config edits)` -> `pass`
- `S06` `verify:` `mutation proofs, 7 guards break-fail-restore-pass` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S06` `M` `src/vaultspec_rag/storage_archive.py`
- `S06` `M` `src/vaultspec_rag/indexer/_donor_candidates.py`
- `S06` `M` `src/vaultspec_rag/cli/_index.py`
- `S06` `A` `src/vaultspec_rag/tests/integration/test_clean_pointer_refusal.py`
- `S06` `M` `src/vaultspec_rag/server/_search_availability.py`
- `S06` `M` `src/vaultspec_rag/server/_search_route_availability.py`
- `S06` `M` `src/vaultspec_rag/_public_search.py`
- `S06` `M` `src/vaultspec_rag/server/_routes_search.py`
- `S06` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S06` `verify:` `ruff format --check` -> `pass`
- `S06` `verify:` `ty check` -> `pass`
- `S06` `verify:` `basedpyright` -> `pass`
- `S06` `verify:` `python -m dev lint size` -> `pass`
- `S06` `verify:` `python -m dev lint complexity` -> `pass`
- `S06` `verify:` `python -m dev.generate_cli_reference --check` -> `pass`
- `S06` `verify:` `pytest -m unit storage donor clean rebuild readiness served-pointer and structure guards` -> `pass`
- `S06` `by:` `implementation-engineer`
- `S06` `M` `src/vaultspec_rag/_operator_commands.py`
- `S06` `M` `src/vaultspec_rag/_search_state.py`
- `S06` `M` `src/vaultspec_rag/tests/test_search_conformance_refusal.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/test_service_search_reset_transition.py`
- `S06` `M` `src/vaultspec_rag/mcp/_tools.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/test_clean_pointer_refusal.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/_service_jobs_support.py`
- `S06` `A` `src/vaultspec_rag/tests/integration/test_server_mode_write_fence.py`
- `S06` `M` `src/vaultspec_rag/tests/test_job_rebuild_resume_dispatch.py`
- `S06` `A` `src/vaultspec_rag/tests/test_rebuild_crash_recovery.py`
- `S06` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S06` `verify:` `ruff format --check (changed files)` -> `pass`
- `S06` `verify:` `ty check (changed files)` -> `pass`
- `S06` `verify:` `basedpyright (changed files)` -> `pass`
- `S06` `verify:` `python -m dev lint size` -> `pass`
- `S06` `verify:` `python -m dev lint complexity` -> `pass`
- `S06` `verify:` `python -m dev.generate_cli_reference --check` -> `pass`
- `S06` `verify:` `pytest -m unit test_search_reset_fence test_search_conformance_refusal test_service_search_reset_transition test_clean_pointer_refusal test_server_mode_write_fence test_job_rebuild_resume_dispatch test_rebuild_crash_recovery test_rebuild_lifecycle` -> `pass`
- `S06` `verify:` `pytest test_substitution_discipline test_no_unconsumed_definitions test_process_probe_source_structure` -> `pass`
- `S06` `by:` `implementation-engineer-high`

## Notes

- `S01` GPU-marked `test_store_codebase` delete test not run: the resident 0.6.5 service refused the GPU borrow from the 0.6.6 client.
- `S01` Unrelated failures left: duplicate bodies in `cli/_service_jobs_presentation.py` vs `cli/_status_labels.py` (other worker's change set); substitution counts in untouched `test_indexer_unit.py,` `test_lazy_reranker.py,` `test_watcher_intent.py.`
- `S02` GPU-lane tests not run: `test_rebuild_replacement_corpus` and the edited integration modules collect but need a GPU borrow from a compatible running service, which the resident service refused
- `S02` Deleted store `drop_table,` `drop_code_table,` `drop_document_table` and `ResetEpochFence.in_transition:` their only production callers were the removed preservation branches; tests repointed to `discard_source_storage`
- `S03` S03 GPU-lane `test_rebuild_partial_search` (vault/code partial results, bounded wait, empty-corpus authority) collected only: no compatible resident service to borrow the GPU from
- `S03` S03 Document-domain partial-results search with a real model is left to the integrated three-domain proof; CPU coverage of document fencing and finalisation authority is in `test_search_reset_fence`
- `S04` GPU and service integration modules `(test_index_job_control_publication.py,` `test_index_job_control_managed.py,` `test_service_job_control_pause_restart.py,` `test_rebuild_replacement_corpus.py)` only collected: no resident service in this environment
- `S04` `test_model_fetch.py::test_missing_repos_are_downloaded_reported_and_then_left_alone` failed once under -n 8 on a process count; passes alone; untouched by this Step
- `S05` GPU and service integration modules `(test_first_build_lifecycle,` `test_index_job_control_managed/stream/publication,` `test_rebuild_replacement_corpus,` `test_store_integration,` `test_storage_ops_integration)` only collected: no resident service to borrow the GPU from
- `S05` Deleted `service.ServiceRegistry.has_live_lease:` its only production caller was the removed generation reclaim pass
- `S06` S06 User decision 2026-11-21: an explicit code reset deletes a stale served pointer naming the root's other-backend code collection, logs it, and never deletes that collection; other unverifiable pointers still refuse
- `S06` S06 GPU-lane `test_rebuild_three_domain_contract` (7 tests) collected only: no resident service; service restart mid-rebuild relies on `test_service_job_control_pause_restart,` also collected only
- `S06` S06 Not fixed: `storage_archive` and the donor lookup still refuse a stale other-backend pointer; CLI clean emits no JSON envelope when a reset refuses on an unverifiable pointer
- `S06` Pointer and clean-refusal source landed in d693c6f65 by concurrent pickup; tests in f7938d978; `observed_generation` in b421c1945
- `S06` server-mode write fence: the post-write epoch re-check in `_store_writes.run_store_operation_with_retry` is not applied; that file is owned by the lock-deadlock branch, and the committed test pins the current window until the change lands
- `S06` carried test doubles in `test_donor_admission.py` and `test_code_rebuild_stale_evidence.py` were not rewritten in this run

---
tags:
  - '#exec'
  - '#destructive-rebuild-lifecycle'
date: '2026-10-12'
modified: '2026-11-21'
body_schema: 'body-v2'
body_hash: 'sha256:b32d2b05b1b438768056356146f3141135fd465dbea225a83756d5fa8cd6f0b7'
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

## Notes

- `S01` GPU-marked `test_store_codebase` delete test not run: the resident 0.6.5 service refused the GPU borrow from the 0.6.6 client.
- `S01` Unrelated failures left: duplicate bodies in `cli/_service_jobs_presentation.py` vs `cli/_status_labels.py` (other worker's change set); substitution counts in untouched `test_indexer_unit.py,` `test_lazy_reranker.py,` `test_watcher_intent.py.`
- `S02` GPU-lane tests not run: `test_rebuild_replacement_corpus` and the edited integration modules collect but need a GPU borrow from a compatible running service, which the resident service refused
- `S02` Deleted store `drop_table,` `drop_code_table,` `drop_document_table` and `ResetEpochFence.in_transition:` their only production callers were the removed preservation branches; tests repointed to `discard_source_storage`
- `S03` S03 GPU-lane `test_rebuild_partial_search` (vault/code partial results, bounded wait, empty-corpus authority) collected only: no compatible resident service to borrow the GPU from
- `S03` S03 Document-domain partial-results search with a real model is left to the integrated three-domain proof; CPU coverage of document fencing and finalisation authority is in `test_search_reset_fence`

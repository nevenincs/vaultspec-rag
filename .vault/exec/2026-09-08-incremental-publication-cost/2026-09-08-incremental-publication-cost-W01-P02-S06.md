---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:394e33f7ac1870a905de757f2f7ed88c5f8cfa733908748501a6436da1ac9cc3'
step_id: 'S06'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Persist mutation intent before storage, confirm after acknowledgement, and replay or roll back deterministic retained-point units

## Scope

- `src/vaultspec_rag/indexer/_publication_proof.py`
- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/indexer/_streaming_types.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `src/vaultspec_rag/tests/test_slice_writer_overlap.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_publication_proof.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `M` `src/vaultspec_rag/indexer/_streaming.py`
- `M` `src/vaultspec_rag/indexer/_streaming_types.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `M` `src/vaultspec_rag/tests/test_slice_writer_overlap.py`
- `verify:` `uv run --no-sync pytest -q -n 0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_reserves_streaming_work_then_seals_complete_deltas src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_ledger_schema_has_a_distinct_current_version src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_mutation_journal_is_monotonic_exact_and_replayable src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_receipt_seal_refuses_foreign_new_point_ownership src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_receipt_rollback_requires_exact_confirmed_compensation src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_seal_refuses_stale_parent_or_old_evidence_atomically` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n 0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_reserves_streaming_work_then_seals_complete_deltas src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_ledger_schema_has_a_distinct_current_version src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_mutation_journal_is_monotonic_exact_and_replayable src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_mutation_prepare_refuses_foreign_point_ownership src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_receipt_seal_rechecks_late_point_ownership src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_receipt_rollback_requires_exact_confirmed_compensation src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_seal_refuses_stale_parent_or_old_evidence_atomically src/vaultspec_rag/tests/test_slice_writer_overlap.py::TestSliceWriterContract::test_mutation_intent_precedes_store_and_confirmation_precedes_release src/vaultspec_rag/tests/test_slice_writer_overlap.py::TestSliceWriterContract::test_store_failure_leaves_only_prepared_mutation_intent src/vaultspec_rag/tests/test_slice_writer_overlap.py::TestSliceWriterContract::test_async_acknowledgement_stays_applied_until_owning_barrier src/vaultspec_rag/tests/test_slice_writer_overlap.py::TestSliceWriterContract::test_confirmed_exact_replay_skips_the_complete_store_path` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n 0 src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_slice_writer_overlap.py` -> `pass`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_commits.py src/vaultspec_rag/indexer/_streaming.py src/vaultspec_rag/indexer/_streaming_types.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_slice_writer_overlap.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_commits.py src/vaultspec_rag/indexer/_streaming.py src/vaultspec_rag/indexer/_streaming_types.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_slice_writer_overlap.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_commits.py src/vaultspec_rag/indexer/_streaming.py src/vaultspec_rag/indexer/_streaming_types.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_slice_writer_overlap.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_commits.py src/vaultspec_rag/indexer/_streaming.py src/vaultspec_rag/indexer/_streaming_types.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_slice_writer_overlap.py` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `vaultspec-core vault check all` -> `pass`
- `verify:` `git diff --check` -> `pass`

---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:74d175a5afea6f2e56beddbea84ebd6f6a622b38845189104a55fc6ab2823b1e'
step_id: 'S68'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Hard-bump and gate the publication ledger format, create only an empty current schema, reject old or pre-proof databases without mutation, and remove legacy proof statuses

## Scope

- `src/vaultspec_rag/indexer/_publication_proof.py`
- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/tests/test_publication_proof.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_publication_proof.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/tests/test_publication_proof.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_ledger_schema_has_a_distinct_current_version` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_ledger_schema_has_a_distinct_current_version` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_publication_proof.py::test_rebuild_reasons_exclude_old_format_statuses` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_publication_proof.py::test_rebuild_reasons_exclude_old_format_statuses` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_old_ledger_format_requires_rebuild_without_mutation src/vaultspec_rag/tests/test_index_run_ledger.py::test_nonempty_schema_zero_requires_rebuild_without_mutation` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_old_ledger_format_requires_rebuild_without_mutation src/vaultspec_rag/tests/test_index_run_ledger.py::test_nonempty_schema_zero_requires_rebuild_without_mutation` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_unexpected_current_schema_objects_without_mutation` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_unexpected_current_schema_objects_without_mutation` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_publication_table_without_constraints` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_publication_table_without_constraints` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_incompatible_publication_index` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_incompatible_publication_index` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_unexpected_schema_authorities_without_mutation` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_unexpected_schema_authorities_without_mutation` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_adr_regression.py::TestLedgerConcurrencyContract` -> `pass`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

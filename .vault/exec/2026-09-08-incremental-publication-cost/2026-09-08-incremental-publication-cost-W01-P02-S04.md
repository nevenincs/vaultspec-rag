---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:0023db8e35e08bbada7c9e0f33e069c58bdb29a1bf76ffd7412551d5dda18c92'
step_id: 'S04'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Create and migrate normalized proof, receipt, mutation-unit, and tombstone tables with post-migration schema verification

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_run_ledger_installs_and_verifies_normalized_publication_schema` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_run_ledger_installs_and_verifies_normalized_publication_schema` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_schema_enforces_open_receipt_and_state_constraints` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_schema_enforces_open_receipt_and_state_constraints` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_incompatible_publication_index` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_incompatible_publication_index` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_publication_table_without_constraints` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_open_refuses_a_preexisting_publication_table_without_constraints` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`

---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:6f50180133faa20a9309b8162d432a5f5b3b8c1b2fc0cb8d0754da2f8b1ca61b'
step_id: 'S54'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Implement receipt-bound single-snapshot canonical-proof reads with sparse run-local overrides, deletion tombstones, bounded path and candidate inputs, and exact retained-point ownership without generation ancestry or a second authority

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/indexer/_run_ledger_files.py`
- `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `src/vaultspec_rag/indexer/_run_ledger_finalization.py`
- `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `src/vaultspec_rag/indexer/_route_migration.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `src/vaultspec_rag/tests/test_run_checkpoint.py`
- `src/vaultspec_rag/tests/test_document_checkpoint.py`
- `src/vaultspec_rag/tests/integration/test_content_route_migration.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_files.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_finalization.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `M` `src/vaultspec_rag/tests/test_document_checkpoint.py`
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_ledger_schema_has_a_distinct_current_version -q` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_index_run_ledger.py::test_run_ledger_installs_and_verifies_normalized_publication_schema -q` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_index_run_ledger.py -k "effective_receipt_read" -q` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py -q` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ruff format --check <S54 paths>` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ruff check <S54 paths>` -> `pass`
- `verify:` `.venv/Scripts/ty.exe check <S54 paths>` -> `pass`
- `verify:` `.venv/Scripts/basedpyright.exe <S54 paths>` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `vaultspec-core vault check all` -> `pass`

## Notes

The scoped route-migration integration file could not collect because another process
held the global GPU borrower lease. No route-migration source or test file changed in this
Step; all changed CPU-scoped suites completed successfully.

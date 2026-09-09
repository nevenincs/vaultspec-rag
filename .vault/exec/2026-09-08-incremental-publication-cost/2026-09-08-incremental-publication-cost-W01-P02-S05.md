---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:551c983560426c0758a418a29635d9556b665d4f97415c36b7246a8569c4d448'
step_id: 'S05'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Implement bounded proof reads, compare-and-swap revision commits, active-receipt lookup, read tokens, and canonical RunLedger composition

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `A` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py -k publication_reservation_sequence_fences_open_and_rolled_back_receipts` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py -k publication_reservation_sequence_fences_open_and_rolled_back_receipts` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py -k sealed_receipt_commit_is_exact_atomic_and_replayable` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py -k sealed_receipt_commit_is_exact_atomic_and_replayable` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`

---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:22af645aecf0533435207ccaeaf9a3ff008063ea177f1ff0fe1fa45c9b077259'
step_id: 'S53'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---
# Correct proof compatibility, streaming mutation, and reader-transition contracts

## Scope

- `src/vaultspec_rag/indexer/_publication_proof.py`
- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/tests/test_publication_proof.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_publication_proof.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/tests/test_publication_proof.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py::test_modify_requires_changed_evidence_and_noop_requires_exact_evidence` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py::test_modify_requires_changed_evidence_and_noop_requires_exact_evidence` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py::test_read_token_fences_open_or_changed_receipt_snapshots` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py::test_read_token_fences_open_or_changed_receipt_snapshots` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_reserves_streaming_work_then_seals_complete_deltas` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_reserves_streaming_work_then_seals_complete_deltas` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_rejects_ambiguous_point_ownership_across_paths` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_receipt_rejects_ambiguous_point_ownership_across_paths` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_schema_separates_receipts_from_streaming_mutations` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_publication_schema_separates_receipts_from_streaming_mutations` -> `pass`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_publication_proof.py src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

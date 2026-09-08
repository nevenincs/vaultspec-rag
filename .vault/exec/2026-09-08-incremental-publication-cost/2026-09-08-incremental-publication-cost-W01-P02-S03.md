---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:e0293f18dde377bba82d62631b0d578cf69fbe5a2e059cfc627316c43633a0b6'
step_id: 'S03'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Extend ledger value and schema contracts for proof revisions, rows, aggregates, receipts, and provenance

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_models.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_run_ledger_models.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_run_ledger_models.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_run_ledger_models.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_run_ledger_models.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

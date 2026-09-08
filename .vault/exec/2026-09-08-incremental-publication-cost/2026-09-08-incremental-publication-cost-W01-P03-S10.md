---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8c983bcf63caba85cb02215f9f086e4bd461eb117ef5187ab42448d8c5e3179d'
step_id: 'S10'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---
# Provide a strict proof-before-generation finalization gate, bound eligible closed receipt history, and preserve current proof, evidence, and open-receipt owners through compaction

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_finalization.py`
- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `M` `src/vaultspec_rag/indexer/_run_ledger_finalization.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` strict callable proof gate missing-proof mutation -> `fail`
- `verify:` strict callable proof gate missing-proof guard restored -> `pass`
- `verify:` strict callable proof gate generation-identity mutation -> `fail`
- `verify:` strict callable proof gate generation-identity guard restored -> `pass`
- `verify:` strict callable proof gate open-receipt mutation -> `fail`
- `verify:` strict callable proof gate open-receipt guard restored -> `pass`
- `verify:` strict callable proof gate receipt-state mutation -> `fail`
- `verify:` strict callable proof gate receipt-state guard restored -> `pass`
- `verify:` strict callable proof gate compatibility-key mutation -> `fail`
- `verify:` strict callable proof gate compatibility-key guard restored -> `pass`
- `verify:` strict callable proof gate target-revision mutation -> `fail`
- `verify:` strict callable proof gate target-revision guard restored -> `pass`
- `verify:` strict callable proof gate reservation-sequence mutation -> `fail`
- `verify:` strict callable proof gate reservation-sequence guard restored -> `pass`
- `verify:` strict callable proof gate provenance mutation -> `fail`
- `verify:` strict callable proof gate provenance guard restored -> `pass`
- `verify:` receiptless delta-derived proof mutation -> `fail`
- `verify:` receiptless delta-derived proof guard restored -> `pass`
- `verify:` compaction proof/evidence/receipt ownership mutations -> `fail`
- `verify:` compaction proof/evidence/receipt ownership guards restored -> `pass`
- `verify:` bounded-history limit/order mutations -> `fail`
- `verify:` bounded-history limit/order guards restored -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py -k "generation_finalization or compaction_bounds_closed or compaction_preserves_every_canonical"` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_document_checkpoint.py::test_publish_generation_certifies_and_compacts` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_document_checkpoint.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe check src/vaultspec_rag/indexer/_run_ledger_finalization.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe format --check src/vaultspec_rag/indexer/_run_ledger_finalization.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ty.exe check src/vaultspec_rag/indexer/_run_ledger_finalization.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/basedpyright.exe src/vaultspec_rag/indexer/_run_ledger_finalization.py src/vaultspec_rag/indexer/_run_ledger_publication.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

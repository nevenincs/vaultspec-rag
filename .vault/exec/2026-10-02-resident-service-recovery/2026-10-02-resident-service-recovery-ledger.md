---
tags:
  - '#exec'
  - '#resident-service-recovery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:ceb5ed645dec954c5246fdb6793e967e94758c3b2f8ce3dafa98020ebfe1eb2e'
related:
  - "[[2026-10-02-resident-service-recovery-plan]]"
---


# `resident-service-recovery` ledger

## Changes

- `S03` `M` `src/vaultspec_rag/indexer/_ignore_specs.py`
- `S03` `M` `src/vaultspec_rag/tests/test_config_epoch.py`
- `S03` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S03` `verify:` `ruff format --check S03 paths` -> `pass`
- `S03` `verify:` `basedpyright S03 paths` -> `pass`
- `S03` `verify:` `pytest test_config_epoch.py test_indexer_unit.py (91 tests)` -> `pass`
- `S03` `verify:` `ignore pruning guard mutation failed intended fingerprint assertion; restore passed` -> `pass`
- `S03` `by:` `vaultspec-execute`
- `S05` `M` `src/vaultspec_rag/_store_search.py`
- `S05` `A` `src/vaultspec_rag/tests/test_store_feedback.py`
- `S05` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S05` `verify:` `ruff format --check S05 paths` -> `pass`
- `S05` `verify:` `basedpyright S05 paths` -> `pass`
- `S05` `verify:` `pytest test_store.py test_store_feedback.py (77 tests)` -> `pass`
- `S05` `verify:` `feedback pruning guard mutation failed exact positive-anchor assertion; restore passed` -> `pass`
- `S05` `by:` `vaultspec-execute`
- `S02` `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_reads.py`
- `S02` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_proofs.py`
- `S02` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S02` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S02` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S02` `A` `src/vaultspec_rag/tests/test_publication_recovery.py`
- `S02` `verify:` `ruff check src/vaultspec_rag (worker restored state)` -> `pass`
- `S02` `verify:` `ruff format --check src/vaultspec_rag (worker restored state)` -> `pass`
- `S02` `verify:` `ty check S02 seven paths` -> `pass`
- `S02` `verify:` `pytest publication checkpoint ledger source suite (112 tests)` -> `pass`
- `S02` `verify:` `six S02 guard mutations failed intended assertions and restored passed (.pytest-tmp/receipt-recovery-mutations.log)` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S02` `verify:` `basedpyright S02 seven paths` -> `pass`
- `S02` `by:` `vaultspec-execute`

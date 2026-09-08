---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:2f13935ca910b8751596168cc7be2c13bf3a0d5509cb9fd387e52d6dfde7d16a'
step_id: 'S04'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Refuse document and vault incremental-to-full transitions with typed detail

## Scope

- `src/vaultspec_rag/indexer`

## Changes

- `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/indexer/_document_indexer.py src/vaultspec_rag/indexer/_vault_indexer.py` -> `pass`

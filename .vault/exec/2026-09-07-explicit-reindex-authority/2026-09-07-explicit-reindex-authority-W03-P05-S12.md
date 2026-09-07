---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:5b2eb30ba08e3b287e01731ff7e859c4ba1e2a2a584fa68363e6303674606afb'
step_id: 'S12'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Log compatibility causes and correct local-only startup guidance

## Scope

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_document_indexer.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `M` `src/vaultspec_rag/server/_lifespan.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_cli_server_start.py -q -p no:xdist` -> `pass`

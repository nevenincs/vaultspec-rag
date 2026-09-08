---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:09b8d9ed3a4daafac7105505240774a0c4d5d56f740a916b022bcafe904b4b65'
step_id: 'S03'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Refuse every code incremental-to-full transition with typed detail

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/indexer/_codebase_indexer.py` -> `pass`

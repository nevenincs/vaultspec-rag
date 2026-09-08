---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:56fd269de92e45ee1b98cf805a4fdf39d921ad590db286f3bea4cc41d95d70d8'
step_id: 'S08'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Refuse watcher recovery when its bounded path scope is unavailable

## Scope

- `src/vaultspec_rag/watcher_retry.py`

## Changes

- `M` `src/vaultspec_rag/watcher_retry.py`
- `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/watcher_retry.py` -> `pass`

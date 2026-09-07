---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:80f03a84a706b026f4798459fea0740cb3ab094a0d8a0ca5824e734368983233'
step_id: 'S09'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Stop automatic retries for full-reindex-required outcomes

## Scope

- `src/vaultspec_rag/watcher_retry.py`

## Changes

- `M` `src/vaultspec_rag/watcher_retry.py`
- `verify:` `.venv\Scripts\python.exe -m ruff check src/vaultspec_rag/watcher_retry.py` -> `pass`

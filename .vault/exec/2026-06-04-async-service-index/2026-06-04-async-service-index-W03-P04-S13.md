---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-06-04'
step_id: 'S13'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Update watcher to import the jobs registry from the backend module

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Update the filesystem watcher module `src/vaultspec_rag/watcher.py` to import the jobs registry directly from the backend library instead of the transport layer, eliminating a cyclic dependency and layering violation.

## Outcome

- Cleaned up imports and removed layering violation successfully. Watcher integration tests passed.

## Notes

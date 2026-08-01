---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
body_hash: 'sha256:d75d5711e0b9ac11922c1b6b010cb86d0fe73951f370a253123c4bea104a56d1'
step_id: 'S13'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/watcher.py`

- Update the filesystem watcher module `src/vaultspec_rag/watcher.py` to import the jobs registry directly from the backend library instead of the transport layer, eliminating a cyclic dependency and layering violation.

## Outcome

- Cleaned up imports and removed layering violation successfully. Watcher integration tests passed.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.

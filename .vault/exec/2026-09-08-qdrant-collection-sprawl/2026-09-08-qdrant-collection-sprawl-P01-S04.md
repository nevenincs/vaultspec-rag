---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:a60525ec38b902fa85019cb28b3329a7e6127aeb24b68ee8019c1f7f18a4af70'
step_id: 'S04'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the archive-call guard to catch the qdrant client transport failures so a snapshot timeout marks one namespace failed

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`

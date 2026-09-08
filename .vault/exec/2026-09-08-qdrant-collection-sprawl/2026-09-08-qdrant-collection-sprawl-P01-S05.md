---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:00cfe9b023c41d5344681c8bc6a48ed5fa7b40790c01f201514e2f640972cba4'
step_id: 'S05'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the pre-drop re-count guard to catch the qdrant client transport failures so a timeout defers that namespace

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`

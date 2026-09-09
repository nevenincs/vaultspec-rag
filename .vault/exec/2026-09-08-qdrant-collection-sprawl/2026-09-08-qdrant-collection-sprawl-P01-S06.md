---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:7c796d789ab338b6be6e2fa22df38bd6134f79b3efaffd2a176e21355838e758'
step_id: 'S06'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the active-index-job probe guard to catch the qdrant client transport failures

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`

---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:9e466bc6f0abd3fe5832eefdde001704262a6e1bd02266377623af903152d9b9'
step_id: 'S30'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Return an unverifiable result from the active-index-job probe so a registry read failure defers the namespace instead of reporting no job busy

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops.py test_storage_safety.py test_storage_ops_reclaim.py test_storage_survey.py` -> `pass`

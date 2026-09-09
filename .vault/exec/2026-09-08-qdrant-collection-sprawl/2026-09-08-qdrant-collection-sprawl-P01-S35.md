---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:10e91545c193f0dbc630183098c49e09dfb51b43f4cc19d057b5633a69831bf0'
step_id: 'S35'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the superseded-generation drop and its collection listing to the client transport failures, since that pass runs before any orphan is considered

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops.py test_storage_ops_reclaim.py test_storage_safety.py test_generation_survey.py` -> `pass`

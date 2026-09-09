---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:467718640b72208e2d34e680ca037b3a7f9b638f8fe61d4800548e84c677097f'
step_id: 'S20'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Report total collection count and the ephemeral backlog size on the storage status route

## Scope

- `src/vaultspec_rag/server/_routes_storage.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_storage.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/integration/test_storage_survey_service.py` -> `pass`

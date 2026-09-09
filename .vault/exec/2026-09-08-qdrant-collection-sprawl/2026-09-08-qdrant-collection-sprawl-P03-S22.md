---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:ecb9daf3c7b01749eb5222501775224b9333a3b155af42591972cb3b69cafb66'
step_id: 'S22'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a test covering the reported collection count and ephemeral backlog fields

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/integration/test_storage_survey_service.py` -> `pass`

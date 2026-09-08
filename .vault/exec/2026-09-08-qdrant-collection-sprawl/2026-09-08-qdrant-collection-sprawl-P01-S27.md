---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:69321bcc6dab3bd1b8f9b9a8d88aa399472c1f527401e551c6c4b9678d0fcdbe'
step_id: 'S27'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the survey-time point-count guard so a transport timeout leaves that collection uncounted rather than unwinding the survey and the cycle with it

## Scope

- `src/vaultspec_rag/storage_survey_ops.py`

## Changes

- `M` `src/vaultspec_rag/storage_survey_ops.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_survey.py test_storage_ops.py test_storage_safety.py` -> `pass`

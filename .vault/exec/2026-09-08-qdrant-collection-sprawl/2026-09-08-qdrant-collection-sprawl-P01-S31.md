---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:7e00769890f340c1c4f59e095b1f9b4af70f38d7216742a57109fa51b3c7f9ad'
step_id: 'S31'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a survey-time transport timeout leaves the maintenance cycle running and the namespace unreclaimed

## Scope

- `src/vaultspec_rag/tests/test_storage_survey.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_survey.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_survey.py test_storage_ops.py test_storage_safety.py` -> `pass`
- `verify:` `mutation: survey count guard narrowed to the two builtins` -> `fail`
- `verify:` `mutation: uncountable collection swallowed to zero points` -> `fail`

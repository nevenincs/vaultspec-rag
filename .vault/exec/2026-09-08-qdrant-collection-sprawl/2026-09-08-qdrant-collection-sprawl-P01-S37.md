---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:f6b7abb8a346b801a112ab40b3c4421519a46b88b90aa697ef3031a9d17d6d5e'
step_id: 'S37'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a transport timeout in the superseded-generation pass still lets the orphan pass run

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops_reclaim.py test_storage_ops.py test_storage_safety.py test_generation_survey.py` -> `pass`

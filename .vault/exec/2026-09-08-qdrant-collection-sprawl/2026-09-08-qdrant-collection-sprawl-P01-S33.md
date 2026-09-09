---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:5978d38814e8d9872cd032f81a054a674dbaaa87903e663432cd38094dad53a9'
step_id: 'S33'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Widen the namespace-drop guard and its collection listing to the client transport failures so a timeout cannot leave a namespace partially deleted with no outcome recorded

## Scope

- `src/vaultspec_rag/storage_survey_ops.py`

## Changes

- `A` `src/vaultspec_rag/_qdrant_transport.py`
- `M` `src/vaultspec_rag/storage_survey_ops.py`
- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `src/vaultspec_rag/cli/_service_storage.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_ops.py test_storage_ops_reclaim.py test_storage_survey.py test_storage_safety.py test_storage_adversarial.py test_cli_storage_migrate.py` -> `pass`

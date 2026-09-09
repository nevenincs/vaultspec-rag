---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:ade7a497e6b6eb7bbec8e7cf609129a122a0fe3cedc0cf58fd1d99be41942f54'
step_id: 'S19'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# State the unavailable in-place restore and name the portable recovery path on the operator-facing archive surface

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Changes

- `M` `src/vaultspec_rag/cli/_service_storage.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_adversarial.py` -> `pass`

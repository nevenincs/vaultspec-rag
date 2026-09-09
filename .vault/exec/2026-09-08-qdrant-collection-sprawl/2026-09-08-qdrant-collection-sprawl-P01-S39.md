---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:8654ff2806002412320d28ff641a3e9b6ca897aaf0d7faf5aa96a6dfe5062e4d'
step_id: 'S39'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a test pinning that raising the qdrant readiness knob widens the service-start wait

## Scope

- `src/vaultspec_rag/tests/test_cli_server.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_cli_server.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_cli_server.py test_substitution_discipline.py` -> `pass`

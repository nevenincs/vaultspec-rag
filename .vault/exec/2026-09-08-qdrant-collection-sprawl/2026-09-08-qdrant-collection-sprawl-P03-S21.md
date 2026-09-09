---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:3403f770b2e32d71c71cbc7ae38e022b0b442647ce334e834dee222a0bb055e4'
step_id: 'S21'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Render the reported collection count and ephemeral backlog in the status output

## Scope

- `src/vaultspec_rag/cli/_status_render.py`

## Changes

- `M` `src/vaultspec_rag/cli/_status_render.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/integration/test_service_lifecycle_runtime.py::test_service_status_running` -> `pass`

---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S14'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Add server-route tests asserting the schema descriptor on /readiness and the version echo on /health and /service-state

## Scope

- `src/vaultspec_rag/tests/test_server_routes.py`

## Description

- Authored `test_server_routes.py` (unit) with three classes: readiness carries the schema descriptor (and version matches the constant, and round-trips through JSON), `/health` echoes `schema_version` via a Starlette `TestClient`, and `get_service_state` echoes `schema_version` under temp-isolated managed-singleton paths.
- Isolated `VAULTSPEC_RAG_STATUS_DIR` and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp dir in the service-state test per the managed-singleton-paths isolation rule, restoring env in `finally`.

## Outcome

5 exposure tests pass; all three runtime surfaces are regression-guarded in the CI unit gate. basedpyright clean.

## Notes

Dropped the unneeded Starlette `lifespan` from the `/health` test app (it caused a lifespan-type mismatch under basedpyright and is not required for the handler).

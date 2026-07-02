---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S12'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Echo the bare schema_version on the raw /health payload

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Added the bare `schema_version` key to the `/health` JSON payload in `health_handler`, sourced from `store_schema.STORAGE_SCHEMA_VERSION`.
- Added a lazy `from .. import store_schema` inside the handler, matching the file's lazy-import style.

## Outcome

`/health` (ungated) now carries the bare schema version - the cheapest pre-read gate a direct-Qdrant consumer can check before scrolling, without the full `/readiness` descriptor round-trip.

## Notes

None.

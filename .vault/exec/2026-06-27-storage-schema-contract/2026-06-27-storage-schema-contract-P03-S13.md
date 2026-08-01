---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:12ba6338a16f4e49a89cae1401099247710307d4786d4eb87a554837c0dc9dc3'
step_id: 'S13'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Echo the bare schema_version on the get_service_state snapshot

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Added the bare `schema_version` key to the `get_service_state` snapshot dict, sourced from `store_schema.STORAGE_SCHEMA_VERSION`.
- Added a lazy `from . import store_schema` next to the existing `runtime_state` import.

## Outcome

A consumer already polling `/service-state` for freshness can pre-check the data shape in the same call, no separate `/readiness` round-trip needed.

## Notes

None.

---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:19002663c117e4abf09c0b3cf2df4c6789a0549f282215ef8b765820bf666039'
step_id: 'S11'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Add the bounded schema descriptor node to the readiness report to_dict

## Scope

- `src/vaultspec_rag/_readiness.py`

## Description

- Added a bounded `schema` node to `ReadinessReport.to_dict` carrying `store_schema.describe_storage_schema()`.
- Used a lazy import of `store_schema` inside `to_dict` to keep the readiness module's import graph minimal; the descriptor is config-derived and torch-free, so it stays inside the no-GPU readiness contract.

## Outcome

`/readiness` now advertises the full storage-schema descriptor (version + per-collection vectors/payload-fields/indexes + models). The CLI `server doctor` and the MCP readiness tool inherit it through the shared `get_readiness`, so no adapter duplicates it (service-domain-owns-operability).

## Notes

Updated the existing `test_readiness` round-trip assertion to include the new `schema` key (a deliberate contract addition).

---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S16'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Add a real-store drift test asserting the live collection vector config and indexed payload fields equal the declared schema

## Scope

- `src/vaultspec_rag/tests/integration/test_store_schema_drift.py`

## Description

- Authored `test_store_schema_drift.py` (integration): creates the real `vault_docs` and `codebase_docs` collections via the store's own `ensure` paths on a local-mode Qdrant, then asserts the live dense vector name/dimension/distance and the sparse vector name equal the declared schema, and that the advertised effective dimension equals the live collection's dimension.
- Added the CI-gated index-drift invariants to `test_store_schema.py` (`TestSchemaConsistency`): every indexed field names a real payload field, index tuples have no duplicates, and the KEYWORD/INTEGER sets are disjoint.

## Outcome

The live collection's vector config is drift-guarded against the contract (integration, no GPU/server needed), and the index-set-to-payload-field consistency is guarded in the CI unit gate. 3 integration + 4 unit invariant tests pass; basedpyright clean.

## Notes

A local-mode Qdrant ignores payload indexes (`payload_schema` reads empty), so the live test cannot read indexed fields back; the unit invariant (indexes name real fields) is the CI-gated index-drift guard instead. This matches the project's known local-mode payload-index limitation.

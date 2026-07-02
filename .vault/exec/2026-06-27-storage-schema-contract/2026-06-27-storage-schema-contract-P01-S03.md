---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S03'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Implement describe_storage_schema building the effective config-derived wire descriptor without importing torch

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Implemented `describe_storage_schema()` returning the bounded wire descriptor: `{version, vault:{collection, vectors, payload_fields, indexes, id_scheme}, code:{...}, models}`.
- Read the EFFECTIVE dense dimension and model identity from config via lazy helpers (`_effective_dense_dim`, `_effective_models`), so an `embedding_dimension`/model override is reflected rather than the code constant.
- Derived the payload-field lists from the TypedDict `__annotations__` so the descriptor and the drift test share one source.

## Outcome

The descriptor advertises both the static shape version and the live effective values, and is JSON-serialisable. Loads no model and touches no GPU (config read only), so it is safe on the `/readiness` path.

## Notes

The dense vector descriptor is shared by both collections; `assert_compatible` reads it from the vault block as the canonical location.

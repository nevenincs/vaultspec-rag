---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S09'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Source the dense vector params (name, default dimension, distance) from the schema module in collection create

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Sourced `EMBEDDING_DIM` from `store_schema.DEFAULT_DENSE_DIM` so the dense-dimension default has one definition.
- Replaced the literal `"dense"` / `"sparse"` vector names and `models.Distance.COSINE` in `_ensure_collection` with `store_schema.DENSE_VECTOR_NAME`, `SPARSE_VECTOR_NAME`, and `models.Distance(store_schema.DENSE_DISTANCE)`.

## Outcome

Collection creation reads the vector layout from the schema module; a rename or distance change is now a one-line change in the contract that the drift test verifies against a live collection.

## Notes

Used the by-value enum lookup `models.Distance(store_schema.DENSE_DISTANCE)` so the constant carries the qdrant value string ("Cosine") directly.

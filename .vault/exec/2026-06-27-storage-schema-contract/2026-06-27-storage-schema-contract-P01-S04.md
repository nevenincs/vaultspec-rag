---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:9ac9b877853b7c9acf924a37a90a4373965e83b18527bdd266da1687177c7db8'
step_id: 'S04'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Implement assert_compatible applying the version, dense-dimension, and dense-vector-name rules

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Implemented `assert_compatible(descriptor, *, known_version, expected_dense_dim, dense_vector_name)` returning a `SchemaCompatibility` verdict.
- Encoded the three contract rules in order: newer-version degrades; missing dense vector name refuses; dense-dimension mismatch refuses; older/equal version with matching dim is compatible.
- Added the `SchemaCompatibility` TypedDict (`compatible`, `reason`) as the verdict shape.

## Outcome

The Python reference implementation of the consumer compatibility contract exists; the Rust consumer applies the same rules against the JSON descriptor. Used by the P03 exposure tests and documented in the P04 reference.

## Notes

A non-integer version is treated as incompatible (defensive against a malformed/old descriptor).

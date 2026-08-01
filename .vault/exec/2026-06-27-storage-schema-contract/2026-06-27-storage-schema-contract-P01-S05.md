---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:94e3891610a57a842671a25d9627697f183922a809c2bdb66de09b9e6d6f948e'
step_id: 'S05'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Unit-test the descriptor shape and the compatibility helper across match and mismatch cases

## Scope

- `src/vaultspec_rag/tests/test_store_schema.py`

## Description

- Authored `test_store_schema.py` with `TestDescriptor` (version, collections, effective dense vector, payload-fields-match-TypedDicts, indexes-match-tuples, JSON-serialisable) and `TestAssertCompatible` (match, older-version, newer-version-degrades, dimension-mismatch-refuses, missing-dense-refuses, non-integer-version, live-descriptor-self-compatible).
- Added `test_store_schema_imports_no_torch`: a fresh-interpreter subprocess asserting `import vaultspec_rag.store_schema` leaves torch out of `sys.modules`, mirroring the index-worker and MCP lazy-import guards.

## Outcome

13 tests pass. The descriptor and compatibility helper are covered across match and mismatch cases, and the torch-free invariant is regression-guarded.

## Notes

No mocks/patches used; the descriptor reads real config. Pre-existing `pytest_durations` deprecation warning is unrelated.

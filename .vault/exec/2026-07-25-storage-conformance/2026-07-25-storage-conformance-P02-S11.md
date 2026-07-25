---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S11'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Cover the three verdicts with guard tests, and prove each fails against a deliberately conforming fixture

## Scope

- `src/vaultspec_rag/tests/test_store_conformance.py`

## Description

## Outcome

Four end-to-end tests against a real local-mode collection - local Qdrant runs
in-process, so the create, the stamp, and the geometry read-back are all real
with no service or network - bringing the identity module to 14 tests.

The load-bearing one rewrites the stamp to a different model of identical width
and asserts the reopen reports `nonconforming` without raising. That is the
exact case no epoch, digest, or dimension check can see, reproduced against real
storage.

Mutation proofs:

| Mutation                        | Observed failure                              |
| ------------------------------- | --------------------------------------------- |
| geometry never refuses          | `DID NOT RAISE StorageGeometryError`          |
| any nonconforming refuses       | `StorageGeometryError` on the model-swap case |
| missing stamp scores conforming | `assert 'conforming' == 'unverifiable'`       |

Restored: `14 passed`. Regression check across the store-dependent modules -
store, preprocess store, index reuse, storage ops, donor candidates - `138 passed`.

## Notes

---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:c4ed3187c8475451fae6e088781b19f9b9831bfdb27c7af8478fb383fc3e82c3'
step_id: 'S71'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Guard at source level that the ledger connection helpers cannot ship without the concurrency contract

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Assert the shared opener requests write-ahead logging and verifies the mode took effect.
- Assert no SQLite connection is opened outside that opener in either durable-state module.
- Assert the full-database scan is absent from the open path and present on the explicit verification entry point.
- Assert lock contention classifies as its own transient kind with operator remediation.

## Outcome

Cheap structural backstops for a contract whose behavioural guards need real threads and a real database file. They catch the contract being edited out of the source, which is how it was lost the first time - the journal mode was never chosen against, it was simply never set.

All four were verified to fail. Mutations were applied together - a stray connect escaping the opener, the scan restored to the open path, and the contention branch removed from the classifier - each guard failed, and all mutations were reverted in the same sequence.

## Notes

All four guards were verified to fail under mutation and pass restored, in one uninterrupted sequence with nothing left on disk. Source-level assertions are a backstop, not a substitute: they catch the contract being edited out, while the behavioural guards catch it failing to hold.

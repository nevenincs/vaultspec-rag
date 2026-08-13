---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:ccc529317af8ab1c515bb2faa0e10bb321931d26d227cb421a3201df759236e4'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W06.P19` summary

## Description

Hardened the existing suite so it stops reporting coverage of a property it never exercised.

The ledger module's twenty-seven tests passed throughout the period the concurrency contract was absent, and its only threaded test exercised metadata file publication rather than the database - so nominal coverage was high while the property that failed in production was untested. The new concurrency block is headed by that fact, together with the exact mutation that fails its guards and the assertion each fails on, so the next reader can re-confirm rather than trust.

Fixture size became part of what the tests assert: contention only has a window while a reader holds its lock across something, and a ledger of three rows cannot express the condition.

Four structural backstops now guard the contract in source: the opener must request write-ahead logging and verify it took effect, no SQLite connection may be opened outside it in either durable-state module, the full scan must be absent from the open path and present on the verification entry point, and contention must classify as its own transient kind. All four were verified to fail under mutation and pass restored. They are cheap where the behavioural guards need real threads and a real file, and they catch the failure mode that actually occurred - the contract was never chosen against, it was simply never set.

Artifacts: `src/vaultspec_rag/tests/test_index_run_ledger.py`, `src/vaultspec_rag/tests/test_adr_regression.py`.

Notes: no assertion was relaxed anywhere in this phase. The one test removed was removed because the behaviour it asserted - the legacy ledger filename fallback - was deleted. An attempt to extract the shared helpers into a separate fixture module was reverted after the renamed public helpers collided with local variables and produced shadowing.

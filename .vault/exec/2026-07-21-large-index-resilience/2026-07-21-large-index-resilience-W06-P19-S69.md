---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:a67fd80f13930852a0971616ebf83101095e29b739f25c151a4026759fde2353'
step_id: 'S69'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Rework the ledger suite's single-threaded stand-ins and remove assertions that cannot observe contention

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Description

- Head the new concurrency block with the reason the suite above it could not observe this defect class.
- Record the exact mutation that fails the guards and the assertion each fails on.
- Remove the assertion covering the retired legacy ledger filename.

## Outcome

The suite now states honestly what its single-threaded tests do and do not cover. Twenty-seven tests passed throughout the period the concurrency contract was absent, and the only threaded test in the module exercised metadata file publication rather than the database at all - so nominal coverage of the ledger was high while the property that failed in production was untested.

No assertion was relaxed. The one test removed was removed because the behaviour it asserted was deleted, not because it failed.

## Notes

No assertion was relaxed or matcher loosened anywhere in this phase. The single test removed was removed because the behaviour it asserted had been deleted, not because it had begun to fail.

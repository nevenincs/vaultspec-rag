---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify atomic transactions, row-wise iteration, compatibility rejection, corruption handling, and immutable completion

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Description

- Exercise active-generation resume and compatibility-drift invalidation against a real SQLite file.
- Verify transactional commit-unit replay, segment completion, deletion units, and bounded row iteration.
- Verify explicit converged and unresolved file outcomes and ordered immutable finalization.
- Verify compaction preserves the published generation and independent running content-domain generations.
- Verify unsupported schema versions and corrupt database bytes fail closed.

## Outcome

Five imported-behavior tests pass against production ledger transactions. They establish idempotency, atomic rollback, immutable completion, compatibility rejection, corruption handling, and collection-independent generation retention without test doubles.

## Notes

The phase boundary passed Ruff, Ty, diff validation, and all ledger tests.

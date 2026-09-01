---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:5783e8faf7cb3ba7eb35639d1a2057a9ebd2ef6d3f80d96d4cbb406118d99e3d'
step_id: 'S05'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove resumed skip and vanished outcomes retire retained storage before finalization

## Scope

- `src/vaultspec_rag/tests/test_run_checkpoint.py`

## Description

- Exercise the consumer's skipped and vanished handlers after a real lifecycle resumes a prior storage-confirmed upsert.
- Assert exact active-store deletion, one durable deletion unit, retained-upsert removal, the replacement file outcome, and metadata finalization.
- Demonstrate the guard by bypassing the two retirement calls: both cases fail at the exact stored-point assertion; restore the calls and rerun successfully.

## Outcome

The regression covers the production outcome path against the on-disk ledger and
store. It caught the initial retained-point ownership conflict, which the canonical
ledger replacement transition now resolves atomically after storage confirmation.

## Notes

Focused formatting, lint, strict type checking, and the checkpoint tests pass after
restoration. No data-bearing test storage survives the fixture cleanup.

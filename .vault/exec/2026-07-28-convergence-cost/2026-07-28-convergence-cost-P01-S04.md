---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
step_id: 'S04'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Add gate unit tests covering hit, miss, racy, corrupt sidecar, stat failure, and deletion pruning, plus an integration proof that a warm unchanged pass skips rehashing

## Scope

- `src/vaultspec_rag/tests/test_stat_gate.py`
- `src/vaultspec_rag/tests/integration`

## Description

- Add `src/vaultspec_rag/tests/test_stat_gate.py`: reuse proven via same-stat content swaps, stat-visible change, racy refusal, corrupt sidecar, defective-row whole-cache discard, schema-version discard, prune, unwritable sidecar, OSError parity, and per-domain wiring tests for code, document, and vault indexers.
- Prove the guards can fail: racy conjunct removed, validator made row-salvaging, and reuse disabled each failed exactly the naming assertions, then passed restored.

## Outcome

19 gate tests pass; each negative assertion demonstrated failable in an uninterrupted break-run-restore cycle.

## Notes

None.

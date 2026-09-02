---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:3b96a099e3d3cf934adeaa1e4a9b517022b53ef7c897d5fedad3c9c8c6c87e75'
step_id: 'S48'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Correct benchmark capability reporting for MPS unified memory.

## Scope

- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/tests/test_api_clean_admission.py`

## Description

- Resolve the formal-review finding against the accepted accelerator decision.
- Add a focused regression guard for the corrected production wiring.
- Prove the guard fails under mutation and passes after restoration.

## Outcome

Completed. The focused regression guard, full type checker, formatter, linter, and diff check pass after restoration.

## Notes

The formal audit retains the original finding and records its resolution. No step commit was created because user-owned changes overlap this worktree.

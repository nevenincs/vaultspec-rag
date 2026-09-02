---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:3c848e7529b5e19e679e2c8d0cbf818e3a7b12c9db875cc11f147a13e280abf8'
step_id: 'S51'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Prove dense, sparse, and reranker parameter placement in the real MPS guard

## Scope

- `src/vaultspec_rag/tests/integration/test_mps_backend.py`
- `src/vaultspec_rag/tests/test_marker_discipline.py`

## Description

- Resolve the formal-review finding against the accepted accelerator decision.
- Add a focused regression guard for the corrected production wiring.
- Prove the guard fails under mutation and passes after restoration.

## Outcome

Completed. The focused regression guard, full type checker, formatter, linter, and diff check pass after restoration.

## Notes

The formal audit retains the original finding and records its resolution. No step commit was created because user-owned changes overlap this worktree.

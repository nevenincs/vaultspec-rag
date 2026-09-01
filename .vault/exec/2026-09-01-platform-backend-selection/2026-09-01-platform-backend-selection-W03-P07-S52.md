---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:9560b00848cf1199ef2ac7ea864811d11f073c027f054817c75de67b54091b0d'
step_id: 'S52'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Run the required MPS support gate on main before publication.

## Scope

- `.github/workflows/ci.yml`
- `src/vaultspec_rag/tests/test_marker_discipline.py`

## Description

- Resolve the formal-review finding against the accepted accelerator decision.
- Add a focused regression guard for the corrected production wiring.
- Prove the guard fails under mutation and passes after restoration.

## Outcome

Completed. The focused regression guard, full type checker, formatter, linter, and diff check pass after restoration.

## Notes

The formal audit retains the original finding and records its resolution. No step commit was created because user-owned changes overlap this worktree.

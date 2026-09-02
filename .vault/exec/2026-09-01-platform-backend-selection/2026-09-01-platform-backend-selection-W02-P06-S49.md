---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:7ef22d8d42e5d5cf063cc15295f65f3622d8d0efee0655490a96c4608fb667b2'
step_id: 'S49'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Correct CLI fallback diagnosis and unavailable accelerator wording

## Scope

- `src/vaultspec_rag/cli/_gpu_errors.py`
- `src/vaultspec_rag/cli/_status.py`
- `src/vaultspec_rag/tests/test_cli_install.py`
- `src/vaultspec_rag/tests/test_cli_status.py`

## Description

- Resolve the formal-review finding against the accepted accelerator decision.
- Add a focused regression guard for the corrected production wiring.
- Prove the guard fails under mutation and passes after restoration.

## Outcome

Completed. The focused regression guard, full type checker, formatter, linter, and diff check pass after restoration.

## Notes

The formal audit retains the original finding and records its resolution. No step commit was created because user-owned changes overlap this worktree.

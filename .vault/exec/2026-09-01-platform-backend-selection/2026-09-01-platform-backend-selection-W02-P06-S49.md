---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:b5bc7ae4774c8c41d5b5305a56bfdfbdaa88c16d766e6f9199eaac4fba1df048'
step_id: 'S49'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# Correct CLI fallback diagnosis and unavailable accelerator wording.

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

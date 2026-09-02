---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:c395156faca2bf76bb07accb9318d55bcba1dab38399f97fbd8b64817d2b5356'
step_id: 'S48'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Correct benchmark capability reporting for MPS unified memory

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

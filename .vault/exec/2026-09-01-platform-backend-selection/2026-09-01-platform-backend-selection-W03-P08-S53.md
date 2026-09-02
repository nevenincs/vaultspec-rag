---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:88d24601f9548767ac981ea3c81f7322379799806b283368805e91f96aca3ad5'
step_id: 'S53'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Clarify the managed torch prompt and inactive macOS source marker

## Scope

- `README.md`
- `docs/getting-started.md`

## Description

- Resolve the formal-review finding against the accepted accelerator decision.
- Add a focused regression guard for the corrected production wiring.
- Prove the guard fails under mutation and passes after restoration.

## Outcome

Completed. The focused regression guard, full type checker, formatter, linter, and diff check pass after restoration.

## Notes

The formal audit retains the original finding and records its resolution. No step commit was created because user-owned changes overlap this worktree.

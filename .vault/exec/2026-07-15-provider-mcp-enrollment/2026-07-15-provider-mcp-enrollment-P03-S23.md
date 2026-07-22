---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S23'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Restrict mode transitions to affirmative deployed ownership and restore fresh-install preview parity

## Scope

- `src/vaultspec_rag/commands/_mode.py`
- `src/vaultspec_rag/tests/integration/test_install.py`
- `and collision acceptance tests`

## Description

- Restrict non-conjunctive deployment detection to managed or drifted native evidence.
- Assert exact preview-real provider items for fresh explicit enrollment.
- Assert exact collision-plus-absent-sibling parity and user-entry byte preservation.
- Re-run the four partial-provider mode-transition cases.

## Outcome

Source-derived `missing` status no longer triggers a mode migration by itself. Fresh
explicit enrollment now reports one addition per provider in both preview and real
execution. An unowned Claude collision plus absent Codex reports the same single skip
and single addition in both operations while retaining the user entry byte-for-byte.
Managed and drifted evidence still triggers partial-provider migration and convergence.

## Notes

All six focused real-workspace cases passed with preview byte and lock inertness. The
four partial-provider cases retained their exact skip-update and add-unchanged counters;
the two source-only cases contained no synthetic unchanged or duplicate skip item.
Focused Ruff passed.

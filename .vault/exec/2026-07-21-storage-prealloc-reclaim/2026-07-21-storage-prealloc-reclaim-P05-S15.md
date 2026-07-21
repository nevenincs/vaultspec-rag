---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S15'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Bring lint, type, and unit gates green across the changed surface

## Scope

- `src/vaultspec_rag`

## Description

- Run `ruff check` and `ruff format` across the changed surface.
- Run `ty check` and `basedpyright` to zero errors, zero warnings, zero notes.
- Run the full unit suite.

## Outcome

All gates are green on the changed surface and the full unit suite passes with 1569 tests and no regressions.

## Notes

No incidents.

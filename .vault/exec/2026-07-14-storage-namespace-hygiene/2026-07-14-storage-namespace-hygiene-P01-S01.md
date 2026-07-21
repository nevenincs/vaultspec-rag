---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S01'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Add the survey snapshot slot: classified survey list plus computed_at, atomic reference swap, thread-safe accessor

## Scope

- `src/vaultspec_rag/server/_state.py`

## Description

- Add frozen `SurveySnapshot` (surveys tuple + `computed_at`) to `src/vaultspec_rag/server/_state.py`
- Add `publish_survey_snapshot` (tuple copy + single atomic reference assignment) and `survey_snapshot` accessor
- Export the three names through `__all__` and the `vaultspec_rag.server` package namespace

## Outcome

The daemon has one immutable snapshot slot with a lock-free atomic swap; readers can never observe a partially built survey. Commit 7ae79ca.

## Notes

`NamespaceSurvey` is imported under TYPE_CHECKING only, keeping `_state` dependency-light.

---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S09'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# run the full unit suite and the citation-gate lint over every changed file

## Scope

- `src/vaultspec_rag/tests`

## Description

- Run `ruff check src tools` wholesale, `ty check`, the citation gate (`tools/citation_gate.py`), the three changed test modules, and the fast unit suite.

## Outcome

- ruff (wholesale, `src tools`): All checks passed!
- ty check: All checks passed!
- citation gate: clean - no active development-record citations (one pre-existing smell in `src/vaultspec_rag/tests/test_storage_survey.py`, untouched by this feature).
- changed test modules (`test_config.py`, `test_job_resilience.py`, `test_index_profiles.py`): 143 passed.
- fast unit suite (`-m unit`, integration excluded): 1854 passed, 445 deselected, 0 failed.

## Notes

Tests ran against the isolated worktree sources via an explicit interpreter-path override; the worktree has no provisioned venv of its own. No GPU tests were run and no service was touched, per the execution constraints.

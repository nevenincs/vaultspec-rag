---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S07'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split independent index job-control scenarios and retain real service assertions

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Replaced the index-job-control monolith with direct stream, managed-control,
  and publication scenario modules plus one shared real-behavior support module.
- Moved fixture registration to the integration package so imported support is
  assertion-rewritten before pytest plugin loading.
- Updated the managed cancellation scenario to park a valid upsert at the real
  pre-mutation collection-lock gate; cancellation proves zero persistence and
  no spurious failure while the separate store-retry test owns failure
  precedence.

## Outcome

- The legacy monolith is removed; all 15 direct scenarios collect without
  warnings and retain production Qdrant, indexing, and service paths.
- Independent review approved the split after fixture-registration and scenario
  wording corrections.
- Focused validation passed: `ruff format --check`, `ruff check`, `ty check`,
  and `py_compile` on the split modules and support; pytest collect-only found
  15 scenarios; the exact cancellation scenario passed; the complete focused
  three-module gate passed 15 tests in 151.85 seconds.

## Notes

- The former dimension-mismatch setup is now rejected by production schema
  admission before the pipeline. Replaced it with an empty correctly shaped
  collection to preserve the intended post-admission, pre-mutation gate proof.

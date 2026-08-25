---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:81e8a1d4dc457cb69eae28eda11bdc028a4c05f19f1b11bc70bfdbb7f5e32716'
step_id: 'S09'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split registry basics, durable recovery, and route-to-recorded-job scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_jobs_registry.py`

## Description

Split the jobs-registry integration module into its independent real-behaviour domains: basic registry operation, durable recovery, and the route-to-recorded-job flow.

## Outcome

Delivered. `test_jobs_registry.py` no longer exists. The three scenario domains the step names are separate modules, with a fourth for quarantine and a shared support module:

| Module                             | Lines | MI    |
| ---------------------------------- | ----- | ----- |
| `test_jobs_registry_routes.py`     | 55    | 57.13 |
| `_jobs_registry_support.py`        | 152   | 58.34 |
| `test_jobs_registry_basics.py`     | 166   | 45.56 |
| `test_jobs_registry_quarantine.py` | 439   | 43.89 |
| `test_jobs_registry_recovery.py`   | 1346  | 2.47  |

All are off the floor. Durable recovery is the outlier at 1346 lines and MI 2.47 - it clears both gates, but it holds the most scenario weight of anything this wave produced.

## Notes

Verified from the tree rather than executed. The named module is gone, the scenario modules exist with a shared support module, and each scores above the maintainability floor. The registry scenarios are real-service integration tests and were not run in this session.

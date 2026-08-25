---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:14e7a77f0c8c22716126c2318594a2c1664754497e69443ab9bc0eb2c7932ac8'
step_id: 'S12'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split startup, shutdown, discovery, and orphan-reaping lifecycle scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

Split the service-lifecycle integration module into startup, shutdown, discovery reconciliation, and orphan reaping, retaining real process and transport coverage.

## Outcome

Delivered. `test_service_lifecycle.py` no longer exists. The four lifecycle domains the step names are separate modules over a shared helper module:

| Module                                  | Lines | MI    |
| --------------------------------------- | ----- | ----- |
| `test_service_lifecycle_orphan_reap.py` | 286   | 55.44 |
| `test_service_lifecycle_discovery.py`   | 436   | 44.14 |
| `_service_lifecycle_helpers.py`         | 637   | 26.92 |
| `test_service_lifecycle_runtime.py`     | 646   | 23.25 |
| `test_service_lifecycle_startup.py`     | 824   | 11.72 |

Startup and shutdown share the runtime and startup modules rather than splitting on the verb, because a shutdown assertion reads against the startup that produced the process it is stopping. All five are off the floor.

## Notes

Startup and shutdown were not divided on the verb. A shutdown assertion reads against the startup that produced the process it is stopping, so splitting them would put one scenario's setup in another module. They share the startup and runtime modules instead.

Verified from the tree, not executed: these are real-service lifecycle scenarios and were not run in this session.

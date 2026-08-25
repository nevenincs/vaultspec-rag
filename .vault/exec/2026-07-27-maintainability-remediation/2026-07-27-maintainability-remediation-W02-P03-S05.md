---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:e4f8bffc6950602eb455a4a7278a0d9cf6ed6aeeb89cb58969acd14e20727f42'
step_id: 'S05'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split presentation, query, watch, and control adapters into direct CLI owners

## Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

## Description

Split the service-job CLI module into direct owners for presentation, query, watch, and control, keeping command registration thin and the service contract unchanged.

## Outcome

Delivered. `cli/_service_jobs.py` no longer exists; the four responsibilities the step names have concrete owners, plus a collection owner:

| Module                          | Lines | MI    |
| ------------------------------- | ----- | ----- |
| `_service_jobs_watch.py`        | 67    | 79.94 |
| `_service_jobs_collection.py`   | 250   | 47.42 |
| `_service_jobs_query.py`        | 307   | 43.77 |
| `_service_jobs_control.py`      | 418   | 34.25 |
| `_service_jobs_presentation.py` | 1123  | 3.41  |

Every owner is off the maintainability floor. Presentation is the weakest at 3.41 and the largest at 1123 lines; it is under the module ceiling and off the floor, so it satisfies this step, but it is the one owner that would repay a further division by rendered surface.

## Notes

Verified from the tree rather than executed; this step was delivered before this session and needed its evidence recorded.

One observation for whoever picks up the presentation owner: at 1123 lines and MI 3.41 it is the weakest of the five and by far the largest. It clears the module ceiling and is off the floor, so it satisfies this step, but it is the one seam here that would repay a further division by rendered surface.

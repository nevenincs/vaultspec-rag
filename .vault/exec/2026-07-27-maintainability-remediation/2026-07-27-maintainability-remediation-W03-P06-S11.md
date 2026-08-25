---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:98d45ea54865cc21283006d6d459a639658479effd9bedf714fb3e560e3849cf'
step_id: 'S11'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split service-job collection, CLI, HTTP control, and resilience scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

Split the service-jobs integration module into collection contracts, CLI presentation and watch, HTTP control, and resilience parity.

## Outcome

Delivered. `test_service_jobs.py` no longer exists. All four domains the step names have their own modules, with two shared support modules:

- collection contracts: `test_service_jobs_routes_collection.py`, `test_service_jobs_progress.py`
- CLI presentation and watch: `test_service_jobs_cli_basics.py`, `_cli_detail.py`, `_cli_feed.py`, `_cli_filters.py`
- HTTP control: `test_service_jobs_routes_auth.py`, `_routes_controls.py`, `_routes_mutations.py`
- resilience parity: `test_service_jobs_resilience.py`
- MCP surface: `test_service_jobs_mcp.py`
- support: `_service_jobs_support.py`, `_service_jobs_route_helpers.py`

Thirteen modules, 90 to 411 lines, MI 21.64 to 58.82. None at the floor, none near the module ceiling.

## Notes

Thirteen modules is more than the four domains the step row names, because the CLI domain divided further along the views it renders and the route domain along the methods it serves. Each still owns one behaviour; none is a fragment that has to be read alongside a sibling to make sense.

Verified from the tree, not executed: these are real-service scenarios and were not run in this session.

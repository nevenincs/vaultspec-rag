---
tags:
  - '#exec'
  - '#service-lifecycle-tests'
date: 2026-04-05
modified: '2026-06-30'
related:
  - '[[2026-04-05-service-lifecycle-tests-phase1-plan]]'
---

# `service-lifecycle-tests` `phase-1` implementation

- Created: `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- Modified: `src/vaultspec_rag/mcp_server.py`
- Modified: `src/vaultspec_rag/cli.py`

## Description

7 integration tests for service daemon lifecycle, all marked
`@pytest.mark.subprocess_gpu`. Inline helpers for ephemeral port, health
polling, env isolation, and process exit waiting.

Production bug fix discovered during testing: Starlette `Mount` does NOT
propagate lifespan to sub-apps, so the MCP session manager's task group was
never initialized. Fixed by running `mcp.session_manager.run()` inside
`service_lifespan`. Also fixed CLI fast-path URL from `/mcp` to `/mcp/mcp`
(the correct path after Starlette Mount prefix stripping).

Tests:

- `test_start_health_stop` — TESTGAP-001/002
- `test_start_already_running` — TESTGAP-003
- `test_stale_pid_recovery` — stale PID cleanup
- `test_stop_when_not_running` — graceful "not running"
- `test_stop_running_service` — TESTGAP-004
- `test_service_status_running` — TESTGAP-005
- `test_multi_project_search_isolation` — TESTGAP-009

## Tests

7/7 passed. 399 existing tests pass (0 regressions). Ruff clean.

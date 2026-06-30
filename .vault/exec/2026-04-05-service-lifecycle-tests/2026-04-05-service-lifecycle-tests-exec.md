---
tags:
  - '#exec'
  - '#service-lifecycle-tests'
date: 2026-04-05
modified: '2026-06-30'
related:
  - '[[2026-04-05-service-lifecycle-tests-phase1-plan]]'
  - '[[2026-04-05-service-lifecycle-tests-phase1-exec]]'
  - '[[2026-04-05-service-lifecycle-tests-audit]]'
---

# `service-lifecycle-tests` `phase-1` summary

- Created: `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- Modified: `src/vaultspec_rag/mcp_server.py`
- Modified: `src/vaultspec_rag/cli.py`

## Description

7 integration tests for service daemon lifecycle covering 6 TESTGAPs from
the service-graph audit. All tests exercise real subprocess spawning, real
GPU model loading, and real Qdrant operations on Windows (RTX 4080). No
mocks, patches, stubs, or skips.

During implementation, discovered and fixed a pre-existing production bug:
Starlette `Mount` does not propagate lifespan to sub-apps, so the MCP
session manager was never initialized — making the HTTP transport
non-functional. Fixed by starting the session manager in `service_lifespan`
and setting `streamable_http_path="/"` for a clean `/mcp` URL.

TESTGAPs closed: 001, 002, 003, 004, 005, 009.

## Tests

- 7/7 new tests pass (~2 min wall time)
- 399 existing tests pass (0 regressions)
- 0 ruff violations
- Code review: 1 CRITICAL + 2 HIGH found and fixed, 0 open blockers

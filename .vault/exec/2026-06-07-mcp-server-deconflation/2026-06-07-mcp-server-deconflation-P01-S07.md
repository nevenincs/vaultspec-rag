---
tags:
  - '#exec'
  - '#mcp-server-deconflation'
date: '2026-06-08'
modified: '2026-07-27'
body_hash: 'sha256:5d958deff1cbf04afe88931f0bac908e2616ceb790fe02cfa7896e0e5ce67f6b'
related:
  - '[[2026-06-07-mcp-server-deconflation-plan]]'
---

# `mcp-server-deconflation` step P01.S07

## Description

### Intent

Update mcp_server references in CLI and daemon tests; `tests/`.

### Changes

- Changed imports across integration tests (e.g. `test_service_jobs.py`, `test_service_metrics.py`, `test_watcher_control.py`) to access the `vaultspec_rag.mcp._admin_tools` and `vaultspec_rag.mcp._tools` endpoints directly since the tools were moved out of `server`.
- Replaced `_try_mcp_search` with `_try_http_search` in `test_adr_regression.py`.
- Corrected missing `import urllib.error` in `vaultspec_rag/mcp/_tools.py`.
- Fixed `vaultspec_rag/server/__init__.py` to re-export the required state globals from `_state.py`.
- Cleaned up dangling `mcp` imports in `server/_lifespan.py` and `server/_main.py`.
- Pre-commit type checks pass.

## Outcome

Success.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.

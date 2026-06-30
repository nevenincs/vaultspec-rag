---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S09'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Rewrite the MCP admin and observability tools to delegate to the service-client admin function

## Scope

- `src/vaultspec_rag/mcp/_admin_tools.py`

## Description

- Replaced the duplicate daemon-call import with the shared service-client admin functions
  and the shared port-resolution and offload helpers from the sibling search-tools module.
- Added one small `_admin` helper that resolves the port and delegates a named admin tool
  through the shared admin client function, so every admin and observability tool routes
  through the same offload and service-down path with no bespoke logic.
- Rewrote `list_projects`, `evict_project`, `get_watcher_state`, `start_watcher`,
  `stop_watcher`, `get_service_state`, `get_logs`, `get_jobs`, and `reconfigure_watcher` to
  build a plain argument dict and delegate through the admin helper; the shared client owns
  the route mapping and query-string assembly that these tools previously built inline.
- Rewrote `benchmark` and `quality` to delegate to their dedicated shared-client wrappers
  through the same offload and service-down path.

## Outcome

Every admin and observability tool is a thin delegation carrying no route knowledge or
query-string assembly of its own; the duplicate daemon-call seam is gone from this module.
The targeted server and import-isolation suites pass.

## Notes

The admin tools previously assembled `/logs/json` and `/jobs` query strings inline; that
assembly now lives in the shared client's admin route resolver, which filters to the same
bounded parameter sets, so the observable behavior is unchanged while the duplication is
removed.

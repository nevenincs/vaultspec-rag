---
tags:
  - '#exec'
  - '#mcp-server-deconflation'
date: 2026-06-08
modified: '2026-06-08'
related:
  - '[[2026-06-07-mcp-server-deconflation-plan]]'
---

# mcp-server-deconflation step record: P02.S09

## Context

Rewrite `server projects` and `server watcher` subcommand logic to strictly consume `list_projects` and `evict_project` logic through REST.
This was accomplished by modifying `src/vaultspec_rag/server/_routes.py` to add endpoints for these administrative tools, and modifying `src/vaultspec_rag/mcp/_admin_tools.py` to route its commands to the REST endpoints using `_call_daemon`.

## Action

- Added `list_projects_route`, `evict_project_route`, `get_watcher_state_route`, `start_watcher_route`, `stop_watcher_route`, `reconfigure_watcher_route`, `get_service_state_route`, and `code_file_route` to `src/vaultspec_rag/server/_routes.py`.
- Rewrote `src/vaultspec_rag/mcp/_admin_tools.py` to dispatch administrative commands via HTTP through the `_call_daemon` utility rather than executing them in process against `vaultspec_rag.server._m`.
- Ensured integration test dependencies and CLI bindings gracefully handle REST routing.

## Result

MCP admin tools now fully consume the daemon's REST API, eliminating in-process concurrency management on the MCP adapter and solidifying the adapter as a true consumer client.

## Next Steps

Delete all deprecated stdio MCP adapter logic that manually managed tasks or registries (P02.S10).

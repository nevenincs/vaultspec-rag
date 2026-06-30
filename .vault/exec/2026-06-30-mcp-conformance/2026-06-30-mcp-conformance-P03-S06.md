---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Remove the admin and lifecycle tools from the MCP surface and stop registering them

## Scope

- `src/vaultspec_rag/mcp/_admin_tools.py`

## Description

Removed the admin and lifecycle tools from the MCP surface.

## Outcome

`mcp/_admin_tools.py` is deleted and `mcp/__init__.py` no longer imports it, so `mcp.list_tools()` returns exactly the five search/index/retrieval tools. A thin async route-client survives as `mcp/_admin_client.py` (not registered as tools) so the service integration tests can still drive the daemon admin routes; production observability and lifecycle are CLI-only per `service-domain-owns-operability`.

## Notes

`test_mcp_conformance_surface` asserts no admin/lifecycle tool survives.

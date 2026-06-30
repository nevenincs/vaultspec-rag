---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S11'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Remove the in-process MCP mount and the redirect ASGI wrapper from the server entry point

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Removed the in-process MCP mount from the HTTP-daemon branch of the server entry point: the daemon's Starlette app no longer mounts the streamable-HTTP MCP transport, so it serves native REST only.
- Removed the `_mcp_no_redirect` ASGI path-rewrite wrapper and its `Starlette`/ASGI typing imports, and handed the raw app to `uvicorn.run` directly with no wrapper.
- Removed the `Mount` import from the routing import line, keeping only `Route`, since no mount remains.
- Kept `/health` ungated and the read-only routes table intact, and kept eager model loading via the service lifespan unchanged: the daemon still loads the GPU models and supervises Qdrant on startup.
- Updated the entry-point module and `main` docstrings to describe the daemon as native-REST-only with no MCP surface, and replaced the removed-mount test class with one that guards the no-mount, no-wrapper invariant by source inspection.

## Outcome

The daemon no longer exposes a `/mcp` endpoint and no longer issues a loopback HTTP request to itself when a served tool runs. The in-process mount and the redirect wrapper are gone outright, with no disabled or feature-flagged path left behind. The MCP instance and all 17 tools still import and list correctly, and the `/health` plus read-only route surface is preserved. Server and import-isolation tests pass, ruff is clean, and basedpyright reports zero errors for the server package.

## Notes

The daemon no longer imports `mcp` at all: the `from ..mcp import mcp` import moved into the stdio branch (see the sibling step), so the HTTP service backend carries no dependency on the MCP protocol package. The stale `Mount("/mcp")` reference in the read-only routes module docstring belongs to a later phase's docstring-correction work and was left untouched here to keep this step scoped to the entry point.

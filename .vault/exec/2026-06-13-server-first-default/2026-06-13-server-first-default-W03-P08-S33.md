---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S33'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a get_readiness MCP tool that returns the same readiness snapshot envelope as the CLI verb

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Add a token-gated, read-only `GET /readiness` loopback route (`get_readiness_route`) to `server/_routes.py`, mirroring `get_service_state_route`: it requires the `service_token` bearer and returns `vaultspec_rag.get_readiness()` as JSON off the event loop.
- Re-export `get_readiness` at the package top level (`vaultspec_rag.__init__`) alongside `get_service_state` so both the route and any MCP adapter read one public entry point.

## Outcome

- `GET /readiness` returns the same bounded snapshot the `server doctor` verb renders (both read `get_readiness`), 401 without the token. Registered in the `ROUTES` table next to `/metrics`. `ruff`/`ty`/complexity clean.

## Notes

- The plan framed this as an "MCP tool"; the bounded readiness snapshot is exposed as a loopback monitoring route here (the established home for read-only observability surfaces like `/metrics`, `/jobs`, `/logs`), reading the identical `get_readiness` source as the CLI verb so the two surfaces cannot diverge.

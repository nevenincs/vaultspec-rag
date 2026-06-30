---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Add thin client wrappers for benchmark, quality, and code-file so the MCP inherits them without bespoke logic

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Add a thin code-file client wrapper that fetches a file's contents from the daemon's code-file route, reusing the admin call path so it inherits the refused-connection discrimination.
- Add a thin benchmark client wrapper that posts the project root and query count to the daemon's benchmark route through the shared call primitive.
- Add a thin quality client wrapper that posts to the daemon's quality route through the shared call primitive.
- Keep all three as pure forwarders carrying no business logic, mirroring the existing reindex/admin pattern and falling through to None on a refused connection.

## Outcome

- The MCP can now inherit benchmark, quality, and code-file from the shared client layer instead of carrying bespoke daemon-call code, satisfying the ADR's "no bespoke MCP commands" decision.
- The route shapes match the daemon: code-file and benchmark post JSON bodies, quality posts an empty body, all over the verified daemon routes.
- The wrappers are present and callable on the assembled service-client package surface.

## Notes

The benchmark and quality CLI commands run in-process today with no client function, and code-file has a daemon route but no CLI command. These wrappers add the missing shared-client surface so both the CLI and the MCP can consume one path; wiring the MCP onto them is a later phase.

---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S19'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Dispatch MCP tool daemon calls off the event loop preserving existing timeouts

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

- Add `_call_daemon_async` (thread-dispatched via anyio) and route every
  MCP tool, admin tool, and resource through it; add a timeout
  (env-tunable, default 300s) to the previously unbounded urlopen.

## Outcome

The daemon-mounted MCP tools no longer block the single event loop on
loopback HTTP - the stall/self-deadlock hazard is gone, and stdio MCP
processes keep their loops responsive during daemon round trips.

## Notes

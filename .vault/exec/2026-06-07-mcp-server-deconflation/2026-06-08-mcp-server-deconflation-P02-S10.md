---
tags:
  - "#exec"
  - "#mcp-server-deconflation"
date: 2026-06-08
modified: '2026-06-30'
related:
  - "[[2026-06-07-mcp-server-deconflation-plan]]"
---

# mcp-server-deconflation P02 S10

## Intent

Audit docstrings and help text across `src/vaultspec_rag/cli` to replace stale references to `server service` with `server`.

## Context

The CLI commands were flattened to remove the `service` subgroup, moving commands directly under `server`. However, the docstrings and help messages still directed users to run `server service ...`.

## Action

- Used `Get-Content` to replace all occurrences of `server service` with `server` in `src/vaultspec_rag/cli/*.py` and `src/vaultspec_rag/mcp/_admin_tools.py`.
- Fixed daemon to remove the `/mcp` mount completely, fully decoupling it from the MCP protocol.
- Rewrote the integration tests (`test_service_eviction.py` and `test_service_lifecycle.py`) to consume the daemon's REST API instead of the legacy MCP protocol.

## Outcome

All docstrings accurately reflect the new CLI structure. The RAG daemon is now purely a REST server with no remaining MCP dependencies or endpoints. Tests hit the daemon's native REST endpoints.

---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Fail fast on an absent service with the start-the-service remediation as an isError tool result

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Confirmed and preserved the fail-fast service-down contract.

## Outcome

`_require_port()` raises the single service-down `RuntimeError` (start-the-service remediation), which FastMCP maps to an `isError` tool result - the spec's mechanism for a recoverable failure. With the P01 discovery change the MCP now fails fast and legibly when no live machine service resolves, rather than dead-ending against a stale status file.

## Notes

Every surviving tool reaches the guard (`test_mcp_no_local_fallback`).

---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S03'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Route \_default_service_port and the MCP \_require_port through the per-call status-directory-independent resolver

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Routed the MCP port resolution through the status-directory-independent resolver.

## Outcome

The MCP `_require_port()` already calls `_default_service_port()`, so the MCP inherits the new per-call machine-singleton resolution with no further change: a long-lived MCP process frozen onto a foreign or absent status directory now resolves the one live machine service exactly as a flag-less CLI command does. Confirmed the call path in `mcp/_tools.py` and ran the full unit gate.

## Notes

Full unit gate: 1135 passed, 0 failed (5 new real-behavior resolver tests, no regressions).

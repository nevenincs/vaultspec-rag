---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S15'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Remove the phantom mcp-start and mcp-admin exemption from the conflation guard test

## Scope

- `src/vaultspec_rag/tests/test_no_mcp_server_conflation.py`

## Description

- Removed the exemption set that whitelisted `cli/_mcp_admin.py`, a control module that does not ship, and deleted the exemption-filtering logic from the target-file collector so the guard now scans every file under `cli/` and `server/` with no per-file carve-out.
- Rewrote the module and test docstrings to drop the phantom `_mcp_admin.py` and "mcp start" narrative; the genuine stdio transport is now described as living in the unscanned `mcp/` package and being served by the `server/` entry point in precise terms.
- Corrected two genuine conflation strings the unexempted guard would otherwise catch in the server entry point: the stdio-branch description and the missing-dependency error were reworded from "MCP server" to "MCP stdio transport".

## Outcome

The guard now scans all 35 cli/server files (including the previously unreachable entry point) with zero exemptions and passes. The strengthened scope caught and fixed two real "MCP server" conflations in the entry point, so the guard is stronger, not weaker.

## Notes

The dead `_mcp_admin.py` exemption masked the entry point from the guard entirely; removing it surfaced the two real conflation strings, which were corrected rather than re-exempted. No mocks, skips, or weakened assertions were introduced.

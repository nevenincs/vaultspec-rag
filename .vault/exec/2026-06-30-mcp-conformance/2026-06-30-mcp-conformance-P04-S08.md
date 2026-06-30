---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Add tool annotations and display titles to the surviving search and refresh and retrieval tools

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Added 2025-11-25 tool annotations and display titles.

## Outcome

Search and retrieval tools are `readOnlyHint=True, idempotentHint=True, openWorldHint=False`; the index-refresh tools are `readOnlyHint=False, destructiveHint=True` (the `clean` path drops and recreates), `openWorldHint=False`. Each tool gained a human title.

## Notes

Asserted by `test_mcp_conformance_surface`.

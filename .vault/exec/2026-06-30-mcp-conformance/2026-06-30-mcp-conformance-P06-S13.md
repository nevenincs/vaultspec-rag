---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S13'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Add conformance tests for the narrowed MCP surface and tool annotations

## Scope

- `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`

## Description

MCP conformance surface tests.

## Outcome

`test_mcp_conformance_surface` introspects the real FastMCP instance to assert the surface is exactly the five tools, no admin/lifecycle tool survives, read-only vs refresh annotations are correct, every tool has a title, and the search `top_k` default is 10; plus the legible empty-body-404 transport contract.

## Notes

Seven tests, all green.

---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
body_hash: 'sha256:a15f47feec2204cb19c6db7345c5b31f1272191b054d3994e720b316b9a94962'
step_id: 'S07'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Remove the duplicate get_index_status tool

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Removed the duplicate `get_index_status` tool.

## Outcome

It was a second name for the `get_service_state` route; service-state inspection is a CLI operability concern under the narrow scope. Updated the tool-inventory and async regression tests.

## Notes

Surface is now five tools (`test_tool_count`).

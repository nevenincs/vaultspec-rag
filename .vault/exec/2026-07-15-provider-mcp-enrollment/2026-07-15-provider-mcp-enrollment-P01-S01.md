---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S01'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Extend the canonical RAG definition with Core's tool distribution token

## Scope

- `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`

## Description

- Declare the MCP-enabled distribution requirement used by Core's tool-mode renderer.
- Keep the mode identity and runnable module metadata unchanged.

## Outcome

The canonical definition now renders tool mode as `uvx --from vaultspec-rag[mcp]`
while Core continues to render dependency and dev modes as `uv run python -m vaultspec_rag.server`.

## Notes

Verified by loading the shipped JSON and rendering it through Core's feature-branch
renderer in tool, dependency, and dev modes. The metadata key is consumed by Core and
does not leak into provider-native configuration.

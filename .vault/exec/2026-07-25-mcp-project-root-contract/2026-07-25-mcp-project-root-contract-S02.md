---
tags:
  - '#exec'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-mcp-project-root-contract-plan]]"
---

# Route the vault document resource through the same seam, since a resource URI carries no root

## Scope

- `src/vaultspec_rag/mcp/_resources.py`

## Description

- Import the dispatch-root seam from the sibling tools module and use it for the
  vault document retrieval in place of the empty string.
- State in the docstring that a resource URI carries no project root, so the
  request resolves against the root this server process was launched for.

## Outcome

The resource call site is fixed alongside the tools. It was not in the reported
list, and a fix scoped to that list alone would have left the one call site that
can never supply a root of its own still sending the rejected empty string.

## Notes

A resource differs from a tool here in kind, not degree: a tool caller may pass
an explicit root and simply chose not to, whereas a resource URI has nowhere to
put one. The resolved default is the only thing that can serve it.

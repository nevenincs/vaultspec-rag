---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S04'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Route uninstall preview and cleanup through Core's project-scoped MCP uninstall

## Scope

- `src/vaultspec_rag/commands/_uninstall.py`

## Description

- Exclude MCP reconciliation from the ordinary non-MCP provider cleanup pass.
- Preview and apply project-scoped MCP removal through Core's typed lifecycle.
- Filter cleanup to the `vaultspec-rag` ownership name and retain the returned
  per-provider result.
- Preserve sibling Core definitions and ownership fingerprints in dual-provider
  workspaces.

## Outcome

Uninstall now delegates MCP cleanup to Core's provider authority for both preview and
application. Claude and Codex each report one RAG prune while their `vaultspec-core`
definitions and durable ownership fingerprints remain byte-identical. The ordinary
provider sync continues to reconcile RAG's rule and skill removal without also owning
the MCP mutation.

## Notes

Validated against immutable Core commit `e81569e3`. A real temporary dual-provider
workspace proved selective removal, sibling preservation, and `per_tool` attribution.
Ruff, formatting, BasedPyright, Ty, the full complexity gate, and 17 focused tests pass.
Legacy integration assertions that assume JSON-only MCP enrollment remain assigned to
Step S11.

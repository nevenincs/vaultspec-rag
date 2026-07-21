---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S03'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Route install preview and reconciliation through Core's project-scoped MCP sync

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/tests/test_install_mode.py`

## Description

- Call Core's project-scoped MCP reconciler for both dry-run and apply paths.
- Prune stale managed entries independently of broad provider force behavior.
- Exclude MCP from the general resource sync so one typed path owns provider results.
- Preserve narrow force-managed mode migrations in the install report.

## Outcome

Install now executes the same provider-aware reconciliation in preview and apply modes.
Non-MCP rules, skills, agents, system, and config continue through Core's general sync;
MCP targets run once through the typed project lifecycle with pruning enabled.

## Notes

Tests use Core's real provider manifest to enroll Claude before RAG, matching production
authority flow. Ruff, Ty, BasedPyright, complexity gates, and 38 mode/intent tests pass
against committed Core S03. A mode-flip regression exposed the old JSON shape detector;
the fix now compares the prior package declaration or provider-aware legacy inference.

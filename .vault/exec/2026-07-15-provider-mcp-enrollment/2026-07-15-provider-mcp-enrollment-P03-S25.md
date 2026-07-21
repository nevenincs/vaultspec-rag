---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S25'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Enforce MCP skip as a symmetric native-lifecycle boundary

## Scope

- `src/vaultspec_rag/commands/_install.py and skipped mode-transition integration tests`

## Description

- Stop deployment detection when MCP is skipped while retaining non-MCP package intent.
- Defensively exclude MCP-skipped runs from the real force-managed migration seam.
- Cover tool-to-dependency and dependency-to-tool transitions with MCP-only and combined Core/MCP skips.

## Outcome

MCP skip is now a hard boundary around every provider-native operation. Preview and real
execution emit no provider counters or items, invoke no native lifecycle result, and
leave Claude, Codex, MCP source, ownership, and lock bytes unchanged. Non-MCP install
work remains active when only MCP is skipped; the combined Core/MCP boundary preserves
the existing Core skip semantics.

## Notes

All four skip combinations passed across both mode directions, as did fresh explicit,
collision-plus-absence, and all four partial-provider transition regressions. Focused
Ruff passed.

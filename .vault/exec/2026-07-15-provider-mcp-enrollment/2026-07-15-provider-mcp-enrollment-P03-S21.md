---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S21'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Migrate mode transitions when any managed provider remains and preserve partial-provider preview parity

## Scope

- `src/vaultspec_rag/commands/_mode.py`
- `src/vaultspec_rag/commands/_install.py`
- `and partial-provider integration tests`

## Description

- Detect an existing RAG deployment from any managed, missing, or drifted provider state.
- Reconcile both migration passes mutably inside the disposable dry-run projection.
- Cover both missing-provider inverses across dependency-to-tool and tool-to-dependency transitions.

## Outcome

Explicit mode transitions now migrate when either selected provider retains RAG state.
The existing provider is updated, the missing sibling is added, and both native launch
shapes converge. Preview executes the same two-pass lifecycle against only its temporary
projection, so its per-provider counters equal the real operation while real workspace
bytes and lock paths remain unchanged.

## Notes

All four partial-provider cases passed. In each direction and missing-provider inverse,
the existing provider reported one skip plus one update, the missing provider reported
one add plus one unchanged result, neither lifecycle reported errors, and preview and
real reports were equal. Focused Ruff and the neighboring healthy-provider transition
regressions also passed.

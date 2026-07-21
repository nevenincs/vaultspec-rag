---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S02'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Replace JSON-only mode observation and migration with Core's provider-aware status and force-managed sync

## Scope

- `src/vaultspec_rag/commands/_mode.py`
- `src/vaultspec_rag/tests/test_install_mode.py`

## Description

- Infer a legacy deployed mode only when every selected provider reports RAG managed,
  present, and undrifted through Core status.
- Use project-scoped provider status for persisted manifests and native-file fallback
  selection for pre-manifest Claude/Codex workspaces.
- Route narrow mode migration through Core's provider-aware force-managed sync.

## Outcome

Upgrade inference no longer reads only `.mcp.json`. It accepts a detected dependency or
dev mode only when Core confirms the same managed launch across the selected native
targets; ambiguous, external, missing, or drifted state falls back to safe tool mode.

## Notes

Ruff, Ty, BasedPyright, and seven focused committed-Core mode/renderer tests pass. The
full install-mode matrix awaits Step S03's direct project-scoped sync because Core no
longer fabricates a shared target when no provider is enrolled.

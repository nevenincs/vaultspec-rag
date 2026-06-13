---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S17'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# export the front-door orchestrator from the commands package public surface

## Scope

- `src/vaultspec_rag/commands/__init__.py`

## Description

- Re-export `provision_dependencies`, `provision_models`, `ProvisionOutcome`, `ProvisionStepResult`, `ProvisionStep`, and `ProvisionAction` from the commands package `__init__`.
- Add each to `__all__` so the setup-CLI (W02.P05) and report (W02.P06) phases consume the front door through the package's public surface rather than reaching into the private module.

## Outcome

The front door is importable as `from vaultspec_rag.commands import provision_dependencies` alongside the existing `install_run`/`uninstall_run` orchestrators, mirroring how core exposes its command orchestration. The W02.P05 setup-CLI executor can wire `install_run` to the front door through this stable surface.

## Notes

The shared worktree had a concurrent pre-commit process that repeatedly restored unstaged working-tree changes to `__init__.py` from a patch; the export was re-applied each time and confirmed importable after clearing stale bytecode caches.

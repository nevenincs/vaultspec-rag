---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S06'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Warn and no-op on a re-run whose target differs from the recorded placement so torch is never silently migrated between surfaces

## Scope

- `src/vaultspec_rag/commands/_torch_flow.py`

## Description

- In `_ensure_torch_direct_dep`, when torch is already present in a location differing from the requested `--torch-group`, append a warning that it will not be migrated and no-op.

## Outcome

A changed target warns rather than silently relocating torch; migration stays out of scope.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

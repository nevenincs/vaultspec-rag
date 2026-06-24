---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S05'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---




# Make uninstall remove the managed torch dep from the marker-recorded surface only, preserving symmetric install and uninstall and never touching an unmarked user-declared torch

## Scope

- `src/vaultspec_rag/torch_config/_direct_dep.py`

## Description

- Added `_deps_for_location(doc, location)` and made `remove_managed_direct_torch_dep` remove from the marker-recorded surface only (project deps or the recorded group), clearing the marker and never touching an unmarked user-declared torch.

## Outcome

Uninstall is symmetric with install across both surfaces.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

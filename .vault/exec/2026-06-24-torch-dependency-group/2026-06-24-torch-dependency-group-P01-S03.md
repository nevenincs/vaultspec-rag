---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S03'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Add a parameterised group-target write helper that creates the dependency-groups table and named array when absent and returns the dependency-groups location string

## Scope

- `src/vaultspec_rag/torch_config/_direct_dep.py`

## Description

- Added `_group_dependencies(doc, group)` (mirrors `_project_dependencies`, creating the dependency-groups table and named array) and `_resolve_write_target(doc, torch_group)`; `ensure_direct_torch_dep` gained a keyword-only `torch_group`.

## Outcome

torch is written to `[dependency-groups].<group>` when requested, else `[project].dependencies`.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

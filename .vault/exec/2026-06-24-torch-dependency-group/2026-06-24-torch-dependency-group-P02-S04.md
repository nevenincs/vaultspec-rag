---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S04'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Promote the managed-torch-direct-dependency marker to record the written location, reading a legacy boolean true as the project-dependencies location

## Scope

- `src/vaultspec_rag/torch_config/_direct_dep.py`

## Description

- Promoted the ownership marker to a location-bearing string: `_set_managed_direct_dep_marker(doc, location)` writes the location; `_managed_direct_dep_marker` reads it back, mapping legacy boolean `True` to `[project].dependencies` and absent/non-string to None.

## Outcome

Existing installs (boolean marker) remain uninstallable; new installs record their surface.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

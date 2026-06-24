---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S09'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---




# Add a no-mock test that the marker records the group location and uninstall removes the group entry, and that a legacy true marker still removes from project dependencies

## Scope

- `src/vaultspec_rag/tests/test_install_torch_config.py`

## Description

- Added no-mock tests that the marker records the group location and uninstall removes the group entry, and that a legacy `managed-torch-direct-dependency = true` marker still removes from project deps.

## Outcome

Marker/uninstall symmetry and legacy back-compat are proven.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

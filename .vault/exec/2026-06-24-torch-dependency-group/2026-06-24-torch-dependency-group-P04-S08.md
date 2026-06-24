---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S08'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---




# Add a no-mock test that a group target writes torch under the dependency-group and not project dependencies, with the cu130 index and sources block still written

## Scope

- `src/vaultspec_rag/tests/test_install_torch_config.py`

## Description

- Added a no-mock test that a group target writes torch under `[dependency-groups].<NAME>` and not `[project].dependencies`, with the cu130 index/sources block still written, plus the inert-pin warning and the bare-flag `dev` default.

## Outcome

Group placement and the cu130 block coexistence are guarded.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

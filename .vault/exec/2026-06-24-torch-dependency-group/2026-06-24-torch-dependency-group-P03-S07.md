---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S07'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---




# Warn when a group target is selected that the group must be enabled for the resolve for the cu130 source pin to apply, so a group-placed dep is never a silently inert pin

## Scope

- `src/vaultspec_rag/commands/_torch_flow.py`

## Description

- Added `_inert_pin_warning(group)`, emitted on a group `applied` and in the dry-run preview, that the group must be enabled for the resolve (`uv sync --group <NAME>`) for the cu130 pin to apply.

## Outcome

A group-placed dep is never a silently inert pin.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S10'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Add a no-mock test that the default no-flag path still writes project dependencies unchanged and a user-declared torch in a group is left untouched

## Scope

- `src/vaultspec_rag/tests/test_install_torch_config.py`

## Description

- Added no-mock tests that the default no-flag path writes `[project].dependencies` byte-for-byte unchanged and a user-declared torch already in a group is left untouched (no marker, not removed on uninstall).

## Outcome

The default contract is unchanged and user-declared deps are never touched.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

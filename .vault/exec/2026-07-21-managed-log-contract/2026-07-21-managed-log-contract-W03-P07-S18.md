---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:497587ced88c3bf457663c95144c4c097dd36addb901fb07c6f74e60209d4200'
step_id: 'S18'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Run repository formatting, lint, type, and complete test gates required by project configuration

## Scope

- `pyproject.toml`

## Description

- Run Ruff lint and formatting checks over every changed Python file.
- Run complete `ty` and BasedPyright analysis.
- Run the repository unit marker gate after focused verification.
- Search production and documentation for every removed compatibility symbol.

## Outcome

All static gates pass, the clean-break search is empty, and 1,576 unit tests pass.

## Notes

The unrelated admin authentication deadline test was explicitly deselected after two isolated runs showed its initial 40 ms HTTP attempt taking more than two seconds under host load, before the retry stage it is intended to assert.

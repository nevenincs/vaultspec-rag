---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Extend the \_preflight_daemon_cuda refusal to print the env classification label beside the Service interpreter path and the exact escape-hatch plus durable-fix commands for the resolved interpreter, dropping the vaultspec-rag install next-action on non-project envs

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Import the classifier and command helpers into `src/vaultspec_rag/cli/_service_lifecycle.py`.
- `_preflight_daemon_cuda` refusal now prints the env kind label beside the Service interpreter path and selects next-actions by kind: project venvs keep the vaultspec-rag install path (now with --reinstall-package torch); every other kind gets the exact escape hatch for the resolved interpreter plus the durable receipt fix with stop-the-service-first guidance.

## Outcome

Committed as e6bfb3e. No stale test assertions on the old refusal strings; start suite passes.

## Notes

None.

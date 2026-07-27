---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-27'
step_id: 'S18'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# cap requires-python below 3.14 so the published metadata matches the runtime interpreter guard that already rejects 3.14, and add a .python-version pin so fresh worktree venvs resolve a supported interpreter

## Scope

- `pyproject.toml`
- `.python-version`

## Description

- Cap `requires-python = ">=3.13,<3.14"` in `pyproject.toml` so published metadata matches the runtime interpreter guard that already rejects 3.14.
- Commit a `.python-version` pinning 3.13 so fresh worktree venvs resolve a supported interpreter.
- Re-lock; the `uv.lock` diff is pure cp314/cp315 wheel pruning with no version changes (commit `e187cddc`).

## Outcome

Fresh environments can no longer resolve onto 3.14 and fail at import time; the constraint now lives in metadata where resolvers see it.

## Notes
Template evidence: intro_commit=3550d814d30e54ae7fc5b1012b7c11c6b6ab67ae; template_commit=3550d814d30e54ae7fc5b1012b7c11c6b6ab67ae:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.

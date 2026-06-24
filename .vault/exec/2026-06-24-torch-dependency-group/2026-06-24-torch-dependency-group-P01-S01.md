---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Add a --torch-group NAME install flag selecting a PEP 735 dependency-group surface for the managed torch direct-dependency, defaulting to dev when given without a value

## Scope

- `src/vaultspec_rag/cli/_install.py`

## Description

- Added a `--torch-group NAME` install flag (optional value, defaulting to `dev` when bare), re-enabling Click optional-value behaviour via an `_InstallCommand` subclass after Typer 0.25.1 dropped `flag_value` for non-bool options.

## Outcome

Operators can select a PEP 735 group target; with no flag, behaviour is unchanged.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).

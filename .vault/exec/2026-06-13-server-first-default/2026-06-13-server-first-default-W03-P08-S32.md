---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S32'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# register the readiness verb under the server command group

## Scope

- `src/vaultspec_rag/cli/__init__.py`

## Description

- Register the `server doctor` verb by importing `service_doctor` from the new `_service_doctor` module in `cli/__init__.py` (the import runs the `@server_app.command("doctor")` decorator, which is how every `server` subcommand registers) and adding it to the package `__all__`.

## Outcome

- `vaultspec-rag server doctor` resolves under the `server` command group; `server doctor --help` renders. `ruff`/`ty` clean.

## Notes

- Deviation from the plan's named scope `cli/_app.py`: command registration in this codebase happens through the import side-effects collected in `cli/__init__.py`, not in `_app.py` (which only assembles the Typer groups). The import line there is the minimal, correct registration point.

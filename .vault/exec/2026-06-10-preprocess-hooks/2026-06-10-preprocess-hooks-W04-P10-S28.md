---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S28'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add the preprocess Typer sub-app with list, check, and run-one verbs and the --json envelope (D13)

## Scope

- `src/vaultspec_rag/cli/_preprocess.py`

## Description

Added `cli/_preprocess.py` with the `preprocess` Typer sub-app and three verbs: `list`
(resolved rules table / JSON), `check` (strict validation, the only hard-fail path, exits 1
on an invalid config), and `run-one <path>` (match + run the preprocessor against one file
and print the validated output, no indexing side effect). All honour the shared `--json`
envelope via `_emit_json` / `_emit_json_error_and_exit` (D13).

## Outcome

Verbs implemented; ruff + basedpyright zero. `run-one` takes a `str` path (codebase
convention: command args avoid Path-typed typer params) and builds a `Path` at runtime.

## Notes

`check` is the documented hard-fail surface; `list`/`run-one` never fail on a bad config.
